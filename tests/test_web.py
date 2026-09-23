from __future__ import annotations

import http.client
import json
import threading
import unittest
from pathlib import Path

from smartmatch.ai import AIConfig, AIService
from smartmatch.web import DEMO_CASES, MAX_REQUEST_BYTES, create_server

ROOT = Path(__file__).resolve().parents[1]


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0, ROOT / "data" / "contractors.csv", ai=AIService(AIConfig()))
        cls.server.RequestHandlerClass.log_message = lambda *args: None
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, path, payload=None, raw=None, headers=None, method="POST"):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        if raw is None and payload is not None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=raw, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if response.headers.get_content_type() == "application/json" else data

    def test_metadata_has_only_public_ai_status(self):
        status, body = self.request("/api/meta", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(set(body["ai"]), {"configured", "provider", "model"})
        self.assertFalse(body["ai"]["configured"])
        self.assertEqual(body["contractors"], 66)

    def test_description_parse_then_recommend(self):
        status, parsed = self.request("/api/parse-brief", {"description": DEMO_CASES[0]["description"], "use_ai": False})
        self.assertEqual(status, 200)
        self.assertEqual(parsed["missing_fields"], [])
        self.assertEqual(parsed["mode"], "local")
        status, result = self.request("/api/recommend", {**parsed["query"], "use_ai": False})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["results"]), 3)
        self.assertFalse(result["ai"]["used"])

    def test_json_shapes_types_and_sizes_are_rejected(self):
        for raw in (b"[]", b"null", b"{", b'{"budget_kzt":NaN}', b'\xff', b'"text"', b"{}" * (MAX_REQUEST_BYTES // 2 + 1)):
            with self.subTest(raw=raw[:30]):
                status, body = self.request("/api/recommend", raw=raw)
                self.assertEqual(status, 400)
                self.assertIn("error", body)
        for payload in ({"description": []}, {"description": "x" * 6001}, {"description": "test", "use_ai": "false"}):
            status, _ = self.request("/api/parse-brief", payload)
            self.assertEqual(status, 400)

    def test_recommend_rejects_nonfinite_and_invalid_fields(self):
        for key, value in (("duration_hours", "NaN"), ("duration_hours", "Infinity"), ("budget_kzt", "Infinity"),
                           ("preferences", []), ("city", " " * 5), ("use_ai", "true")):
            with self.subTest(key=key, value=value):
                status, body = self.request("/api/recommend", {**DEMO_CASES[0]["query"], key: value})
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_cross_origin_and_wrong_content_type_rejected(self):
        status, _ = self.request("/api/parse-brief", {"description": "brief"}, headers={"Origin": "https://other.example"})
        self.assertEqual(status, 403)
        status, _ = self.request("/api/recommend", {}, headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 400)

    def test_dotenv_and_parent_files_are_not_served(self):
        for path in ("/.env", "/../ai.py", "/../data/contractors.csv"):
            with self.subTest(path=path):
                status, _ = self.request(path, method="GET")
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
