from __future__ import annotations

import argparse
import json
import mimetypes
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .ai import AIConfig, AIService, _strict_json, recommend_with_ai
from .brief import MAX_DESCRIPTION, parse_brief
from .engine import RecommendationEngine
from .models import SearchQuery
from .repository import ContractorRepository


ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_DATA = ROOT / "data" / "contractors.csv"
MAX_REQUEST_BYTES = 32_768

DEMO_CASES = [
    {
        "name": "Плотная категория",
        "description": "Нужен интеллигентный ведущий на корпоратив в Алматы 15 октября 2026 года. Бюджет до 1,5 млн тенге, 6 часов, русский язык. Для бизнес-аудитории, без навязчивых конкурсов.",
        "query": {
            "city": "Алматы", "event_date": "2026-10-15", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 1500000, "duration_hours": 6,
            "language": "русский", "preferences": "интеллигентный ведущий для бизнес-аудитории",
        },
    },
    {
        "name": "Редкая категория",
        "description": "Ищем флориста на свадьбу в Алматы 15 октября 2026 года. Бюджет до 700 000 тенге. Русский язык. Нужно авторское цветочное оформление.",
        "query": {
            "city": "Алматы", "event_date": "2026-10-15", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 700000, "duration_hours": None,
            "language": "русский", "preferences": "авторское цветочное оформление",
        },
    },
    {
        "name": "Условия не проходят",
        "description": "Нужен ведущий на корпоратив в Алматы 31 декабря 2026 года. Бюджет до 100 000 тенге, 8 часов, казахский язык.",
        "query": {
            "city": "Алматы", "event_date": "2026-12-31", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 100000, "duration_hours": 8,
            "language": "казахский", "preferences": "",
        },
    },
    {
        "name": "Категории нет",
        "description": "Нужен флорист на свадьбу за рубежом 15 октября 2026 года. Бюджет до 1 млн тенге, русский язык.",
        "query": {
            "city": "Зарубежье", "event_date": "2026-10-15", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 1000000, "duration_hours": None,
            "language": "русский", "preferences": "",
        },
    },
]


class SmartMatchHandler(BaseHTTPRequestHandler):
    engine: RecommendationEngine
    ai: AIService

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/meta":
            self._json({**self.engine.repository.metadata(), "demo_cases": DEMO_CASES, "ai": self.ai.status()})
            return
        if path == "/api/health":
            self._json({"status": "ok", "contractors": len(self.engine.repository.contractors)})
            return
        if path == "/":
            path = "/index.html"
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/recommend", "/api/parse-brief"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json({"error": "Запрос разрешён только со страницы этого сайта"}, HTTPStatus.FORBIDDEN)
            return
        try:
            payload = self._read_payload()
            if "use_ai" in payload and not isinstance(payload["use_ai"], bool):
                raise ValueError("Поле use_ai должно быть логическим значением")
            if path == "/api/parse-brief":
                result = parse_brief(payload.get("description"), self.engine.repository.metadata(), self.ai, payload.get("use_ai", True))
            else:
                self._validate_query_payload(payload)
                result = recommend_with_ai(self.engine, SearchQuery.from_dict(payload), self.ai, payload.get("use_ai", True))
        except (ValueError, TypeError, OverflowError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except (socket.timeout, TimeoutError):
            self._json({"error": "Время ожидания запроса истекло"}, HTTPStatus.REQUEST_TIMEOUT)
            return
        self._json(result)

    def _read_payload(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Отправьте запрос в формате application/json")
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Потоковые запросы не поддерживаются")
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit() or len(raw_length) > 8:
            raise ValueError("Некорректная длина запроса")
        length = int(raw_length)
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError(f"Размер запроса должен быть от 1 до {MAX_REQUEST_BYTES} байт")
        self.connection.settimeout(10)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("Запрос получен не полностью")
        try:
            payload = _strict_json(raw.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("Некорректный JSON запроса") from None
        if not isinstance(payload, dict):
            raise ValueError("Запрос должен быть JSON-объектом")
        return payload

    @staticmethod
    def _validate_query_payload(payload: dict) -> None:
        for key in ("city", "event_date", "event_format", "category", "language", "preferences"):
            value = payload.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"Поле {key} должно быть строкой")
            if key in {"city", "event_date", "event_format", "category"} and not value.strip():
                raise ValueError(f"Не заполнено поле {key}")
            if len(value) > (MAX_DESCRIPTION if key == "preferences" else 120):
                raise ValueError(f"Поле {key} слишком длинное")
        if "use_ai" in payload and not isinstance(payload["use_ai"], bool):
            raise ValueError("Поле use_ai должно быть логическим значением")

    def _static(self, request_path: str) -> None:
        relative = request_path.lstrip("/")
        target = (STATIC / relative).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def create_server(host: str, port: int, data_path: Path, ai: AIService | None = None) -> ThreadingHTTPServer:
    repository = ContractorRepository.from_csv(data_path)
    engine = RecommendationEngine(repository)
    ai = ai if ai is not None else AIService(AIConfig.from_env(ROOT))
    handler = type("ConfiguredSmartMatchHandler", (SmartMatchHandler,), {"engine": engine, "ai": ai})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartMatch demo server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.data)
    print(f"SmartMatch: http://{args.host}:{args.port}")
    print(f"Каталог: {len(server.RequestHandlerClass.engine.repository.contractors)} профилей")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
