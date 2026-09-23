from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .engine import RecommendationEngine
from .models import SearchQuery
from .repository import ContractorRepository


ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_DATA = ROOT / "data" / "contractors.csv"

DEMO_CASES = [
    {
        "name": "Плотная категория",
        "description": "Ведущий для корпоративного вечера в Алматы",
        "query": {
            "city": "Алматы", "event_date": "2026-10-15", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 1500000, "duration_hours": 6,
            "language": "русский", "preferences": "интеллигентный ведущий для бизнес-аудитории",
        },
    },
    {
        "name": "Редкая категория",
        "description": "Флорист на осеннюю свадьбу",
        "query": {
            "city": "Алматы", "event_date": "2026-10-15", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 700000, "duration_hours": None,
            "language": "русский", "preferences": "авторское цветочное оформление",
        },
    },
    {
        "name": "Условия не проходят",
        "description": "Минимальный бюджет в плотную декабрьскую дату",
        "query": {
            "city": "Алматы", "event_date": "2026-12-31", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 100000, "duration_hours": 8,
            "language": "казахский", "preferences": "",
        },
    },
    {
        "name": "Категории нет",
        "description": "Отдельный сценарий отсутствующего рынка",
        "query": {
            "city": "Зарубежье", "event_date": "2026-10-15", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 1000000, "duration_hours": None,
            "language": "русский", "preferences": "",
        },
    },
]


class SmartMatchHandler(BaseHTTPRequestHandler):
    engine: RecommendationEngine

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/meta":
            self._json({**self.engine.repository.metadata(), "demo_cases": DEMO_CASES})
            return
        if path == "/api/health":
            self._json({"status": "ok", "contractors": len(self.engine.repository.contractors)})
            return
        if path == "/":
            path = "/index.html"
        self._static(path)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/recommend":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = self.engine.recommend(SearchQuery.from_dict(payload))
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._json(result)

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
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def create_server(host: str, port: int, data_path: Path) -> ThreadingHTTPServer:
    repository = ContractorRepository.from_csv(data_path)
    engine = RecommendationEngine(repository)
    handler = type("ConfiguredSmartMatchHandler", (SmartMatchHandler,), {"engine": engine})
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

