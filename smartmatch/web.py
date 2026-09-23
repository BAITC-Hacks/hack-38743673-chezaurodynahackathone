from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import sqlite3
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .ai import AIConfig, AIService, _strict_json
from .brief import MAX_DESCRIPTION
from .engine import RecommendationEngine
from .database import DEFAULT_DATABASE, Database
from .samples import DEMO_CASES
from .service import MatchingService


ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_DATA = ROOT / "data" / "contractors.csv"
DEFAULT_DB = DEFAULT_DATABASE
MAX_REQUEST_BYTES = 32_768




class SmartMatchHandler(BaseHTTPRequestHandler):
    engine: RecommendationEngine
    ai: AIService
    service: MatchingService

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/meta":
            self._json({**self.engine.repository.metadata(), "demo_cases": DEMO_CASES, "ai": self.ai.status(),
                        "storage": {"enabled": True, "engine": "sqlite"}})
            return
        if path == "/api/health":
            try:
                self.service.database.stats()
            except sqlite3.Error:
                self._json({"status": "unavailable", "database": "unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._json({"status": "ok", "contractors": len(self.engine.repository.contractors), "database": "ok"})
            return
        if path == "/":
            path = "/index.html"
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/recommend", "/api/parse-brief", "/api/selection"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_payload()
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._json({"error": "Запрос разрешён только со страницы этого сайта"}, HTTPStatus.FORBIDDEN)
                return
            if "use_ai" in payload and not isinstance(payload["use_ai"], bool):
                raise ValueError("Поле use_ai должно быть логическим значением")
            if path == "/api/parse-brief":
                result = self.service.parse(payload.get("description"), payload.get("use_ai", True))
            elif path == "/api/selection":
                for key in ("search_id", "contractor_id"):
                    if not isinstance(payload.get(key), str) or not 1 <= len(payload[key]) <= 120:
                        raise ValueError(f"Некорректное поле {key}")
                created = self.service.database.record_selection(payload["search_id"], payload["contractor_id"])
                result = {"saved": True, "created": created}
            else:
                self._validate_query_payload(payload)
                result = self.service.recommend(payload)
        except (ValueError, TypeError, OverflowError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except sqlite3.Error:
            self._json({"error": "База данных временно недоступна. Повторите запрос."}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        except (socket.timeout, TimeoutError):
            self._json({"error": "Время ожидания запроса истекло"}, HTTPStatus.REQUEST_TIMEOUT)
            return
        self._json(result)

    def _read_payload(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Потоковые запросы не поддерживаются")
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit() or len(raw_length) > 8:
            raise ValueError("Некорректная длина запроса")
        length = int(raw_length)
        self.connection.settimeout(10)
        if MAX_REQUEST_BYTES < length <= 2 * MAX_REQUEST_BYTES:
            # Drain a bounded overflow before replying to avoid a Windows TCP reset.
            self.rfile.read(length)
        if not 0 < length <= MAX_REQUEST_BYTES:
            raise ValueError(f"Размер запроса должен быть от 1 до {MAX_REQUEST_BYTES} байт")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("Запрос получен не полностью")
        # Drain bounded bodies before rejecting headers. Otherwise Windows may
        # reset the socket while the client is still sending its request body.
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Отправьте запрос в формате application/json")
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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def create_server(host: str, port: int, data_path: Path, ai: AIService | None = None,
                  db_path: Path = DEFAULT_DB) -> ThreadingHTTPServer:
    ai = ai if ai is not None else AIService(AIConfig.from_env(ROOT))
    service = MatchingService(Database(db_path), data_path, ai)
    handler = type("ConfiguredSmartMatchHandler", (SmartMatchHandler,),
                   {"engine": service.engine, "ai": ai, "service": service})
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartMatch MVP: каталог, подбор и история в SQLite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Путь к постоянной SQLite-базе")
    parser.add_argument("--open-browser", action="store_true", help="Открыть сайт после запуска сервера")
    args = parser.parse_args()
    try:
        server = create_server(args.host, args.port, args.data, db_path=args.db)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(f"Не удалось запустить сервер: {exc}")
    print(f"SmartMatch: http://{args.host}:{args.port}")
    print(f"Каталог: {len(server.RequestHandlerClass.engine.repository.contractors)} профилей")
    print(f"База данных: {args.db.resolve()}")
    if args.open_browser:
        browser_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
        webbrowser.open(f"http://{browser_host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
