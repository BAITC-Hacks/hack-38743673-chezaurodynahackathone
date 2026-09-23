from __future__ import annotations

import copy
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from smartmatch.ai import AIConfig, AIService, recommend_with_ai, validate_ranking
from smartmatch.brief import EXTRACTED_FIELDS, extract_local, parse_brief, validate_extraction
from smartmatch.engine import RecommendationEngine
from smartmatch.models import SearchQuery
from smartmatch.repository import ContractorRepository
from smartmatch.web import DEMO_CASES

ROOT = Path(__file__).resolve().parents[1]


def response(value):
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(value, ensure_ascii=False)}]}]}


class BriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = ContractorRepository.from_csv(ROOT / "data" / "contractors.csv").metadata()

    def test_complete_russian_demo_briefs(self):
        for demo in DEMO_CASES:
            with self.subTest(demo=demo["name"]):
                query, warnings = extract_local(demo["description"], self.meta)
                for field, value in demo["query"].items():
                    if field != "preferences" and value is not None:
                        self.assertEqual(query[field], value)
                self.assertEqual(warnings, [])

    def test_no_defaults_for_missing_requirements(self):
        result = parse_brief("Нужен интеллигентный ведущий", self.meta, AIService(AIConfig()))
        self.assertEqual(result["query"]["category"], "Ведущий")
        self.assertEqual(set(result["missing_fields"]), {"city", "event_date", "event_format", "budget_kzt"})
        self.assertNotIn("duration_hours", result["query"])
        self.assertNotIn("language", result["query"])

    def test_incomplete_date_does_not_infer_year(self):
        query, warnings = extract_local("Свадьба 15 октября в Алматы", self.meta)
        self.assertNotIn("event_date", query)
        self.assertTrue(warnings)

    def test_ambiguous_values_are_left_blank(self):
        query, warnings = extract_local("Ведущий в Алматы или Астане. 15.10.2026 или 16.10.2026. Русский и казахский.", self.meta)
        for field in ("city", "event_date", "language"):
            self.assertNotIn(field, query)
        self.assertEqual(len(warnings), 3)

    def test_guests_and_time_are_not_budget(self):
        query, _ = extract_local("Ведущий на 6 часов, 100 гостей, 15.10.2026", self.meta)
        self.assertNotIn("budget_kzt", query)
        self.assertEqual(query["duration_hours"], 6)

    def test_negated_language_is_not_required(self):
        query, _ = extract_local("Ведущий на русском, без английского", self.meta)
        self.assertEqual(query["language"], "русский")

    def test_duration_boundary_matches_search_validation(self):
        query, warnings = extract_local("Ведущий на 24 часа", self.meta)
        self.assertEqual(query["duration_hours"], 24)
        self.assertEqual(warnings, [])
        for hours in (0, -2, 24.5, 25, 168):
            with self.subTest(hours=hours):
                query, warnings = extract_local(f"Ведущий на {hours} часов", self.meta)
                self.assertNotIn("duration_hours", query)
                self.assertTrue(warnings)
        raw = {key: {"value": None, "quote": None} for key in EXTRACTED_FIELDS}
        raw["duration_hours"] = {"value": "25", "quote": "25 часов"}
        with self.assertRaises(ValueError):
            validate_extraction(raw, "25 часов", self.meta)

    def test_explicit_foreign_currency_is_not_treated_as_tenge(self):
        for text in ("Бюджет 5 тыс рублей", "Бюджет 500 USD", "Бюджет $5 тыс", "Бюджет 10 000 евро"):
            with self.subTest(text=text):
                query, warnings = extract_local(text, self.meta)
                self.assertNotIn("budget_kzt", query)
                self.assertTrue(warnings)

    def test_grounded_model_extraction(self):
        text = "В Алматы 15 октября 2026 года. Бюджет до 1,5 млн тенге, 6 часов."
        raw = {key: {"value": None, "quote": None} for key in EXTRACTED_FIELDS}
        for key, value, quote in (("city", "Алматы", "Алматы"), ("event_date", "2026-10-15", "15 октября 2026"),
                                  ("budget_kzt", "1500000", "Бюджет до 1,5 млн тенге"), ("duration_hours", "6", "6 часов")):
            raw[key] = {"value": value, "quote": quote}
        query, warnings = validate_extraction(raw, text, self.meta)
        self.assertEqual(query["budget_kzt"], 1500000)
        self.assertEqual(query["duration_hours"], 6)
        self.assertEqual(warnings, [])
        raw["city"]["quote"] = "Москва"
        with self.assertRaises(ValueError):
            validate_extraction(raw, text, self.meta)

    def test_model_cannot_make_up_date_year_or_numeric_budget(self):
        raw = {key: {"value": None, "quote": None} for key in EXTRACTED_FIELDS}
        raw["event_date"] = {"value": "2026-10-15", "quote": "15 октября"}
        raw["budget_kzt"] = {"value": "500000", "quote": "100 гостей"}
        query, warnings = validate_extraction(raw, "15 октября, 100 гостей", self.meta)
        self.assertNotIn("event_date", query)
        self.assertNotIn("budget_kzt", query)
        self.assertEqual(len(warnings), 2)

    def test_disabled_ai_and_timeout_fallback(self):
        calls = []
        def fail(*args):
            calls.append(args)
            raise TimeoutError()
        ai = AIService(AIConfig(api_key="unit-test-token"), transport=fail)
        brief = DEMO_CASES[0]["description"]
        result = parse_brief(brief, self.meta, ai, use_ai=False)
        self.assertEqual(result["mode"], "local")
        self.assertEqual(calls, [])
        fallback = parse_brief(brief, self.meta, ai)
        self.assertEqual(fallback["mode"], "local")
        self.assertIn("недоступен", fallback["message"])
        self.assertEqual(fallback["query"], result["query"])

    def test_brief_limits(self):
        for text in (None, [], "", "   ", "x" * 6001):
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                parse_brief(text, self.meta, AIService(AIConfig()))


class AIServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = ContractorRepository.from_csv(ROOT / "data" / "contractors.csv")
        cls.engine = RecommendationEngine(cls.repository)
        cls.query = SearchQuery.from_dict(DEMO_CASES[0]["query"])

    def test_root_dotenv_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text('OPENAI_API_KEY="file-token"\nSMARTMATCH_AI_MODEL=file-model\nSMARTMATCH_AI_TIMEOUT=nan\n', encoding="utf-8")
            config = AIConfig.from_env(root, {"OPENAI_API_KEY": "environment-token"})
        self.assertTrue(config.configured)
        self.assertEqual(config.api_key, "environment-token")
        self.assertEqual(config.model, "file-model")
        self.assertEqual(config.timeout, 8)
        self.assertNotIn(config.api_key, repr(config))
        self.assertNotIn(config.api_key, json.dumps(AIService(config).status()))

    def test_insecure_external_provider_url_is_rejected(self):
        self.assertFalse(AIConfig(api_key="unit-test-token", base_url="http://example.com").configured)
        self.assertTrue(AIConfig(provider="compatible", api_key="unit-test-token", base_url="http://localhost:1234/v1").configured)

    def test_openai_request_and_session_cache(self):
        calls = []
        def transport(url, headers, payload, timeout):
            calls.append((url, headers, payload, timeout))
            return response({"ok": 1})
        service = AIService(AIConfig(api_key="unit-test-token"), transport=transport)
        args = ("test", {"type": "object"}, "instructions", {"text": "brief"})
        first = service.generate(*args, validator=lambda value: value)
        first["ok"] = 100
        second = service.generate(*args, validator=lambda value: value)
        self.assertEqual(second, {"ok": 1})
        self.assertEqual(len(calls), 1)
        url, headers, payload, timeout = calls[0]
        self.assertTrue(url.endswith("/responses"))
        self.assertEqual(headers["Authorization"], "Bearer unit-test-token")
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertFalse(payload["store"])
        self.assertEqual(timeout, 8)

    def test_concurrent_identical_requests_call_provider_once(self):
        calls = []
        def transport(*args):
            calls.append(1)
            time.sleep(0.02)
            return response({"value": 42})
        service = AIService(AIConfig(api_key="unit-test-token"), transport=transport)
        def generate(_):
            return service.generate("test", {}, "prompt", {}, validator=lambda value: value)
        with ThreadPoolExecutor(max_workers=4) as pool:
            values = list(pool.map(generate, range(4)))
        self.assertEqual(values, [{"value": 42}] * 4)
        self.assertEqual(calls, [1])

    def test_cache_is_bounded_and_invalid_answers_not_cached(self):
        calls = []
        def transport(*args):
            calls.append(1)
            return response({"value": 42})
        service = AIService(AIConfig(api_key="unit-test-token"), transport=transport, cache_size=2)
        for index in range(3):
            service.generate("test", {}, "prompt", {"i": index}, validator=lambda value: value)
        self.assertEqual(len(service._cache), 2)
        def reject(value):
            raise ValueError("Rejected")
        for _ in range(2):
            with self.assertRaises(ValueError):
                service.generate("invalid", {}, "prompt", {}, validator=reject)
        self.assertEqual(len(calls), 5)

    def test_alternative_provider_adapters(self):
        for provider in ("gemini", "compatible"):
            calls = []
            def transport(url, headers, payload, timeout):
                calls.append((url, headers, payload))
                content = json.dumps({"ok": True})
                if provider == "gemini":
                    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}]}
                return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
            service = AIService(AIConfig(provider=provider, api_key="unit-test-token"), transport=transport)
            self.assertEqual(service.generate("test", {}, "prompt", {}, validator=lambda value: value), {"ok": True})
            if provider == "gemini":
                self.assertTrue(calls[0][0].endswith(":generateContent"))
                self.assertIn("x-goog-api-key", calls[0][1])
                self.assertNotIn("unit-test-token", calls[0][0])
            else:
                self.assertTrue(calls[0][0].endswith("/chat/completions"))

    def test_only_eligible_profiles_reach_model_and_quotes_are_preserved(self):
        seen = []
        def transport(url, headers, payload, timeout):
            data = json.loads(payload["input"])
            seen.extend(data["candidates"])
            return response({"candidates": [{"id": item["id"], "score": 100 - index,
                        "quote": item["description"][:100]} for index, item in enumerate(data["candidates"])]})
        result = recommend_with_ai(self.engine, self.query, AIService(AIConfig(api_key="unit-test-token"), transport=transport))
        allowed = self.engine.recommend(self.query, limit=100)["results"]
        self.assertEqual({row["id"] for row in seen}, {row["id"] for row in allowed})
        self.assertTrue(result["ai"]["used"])
        self.assertEqual(len(result["results"]), 3)
        by_id = {item.id: item for item in self.repository.contractors}
        for row in result["results"]:
            self.assertIn(by_id[row["id"]].description[:100], row["explanation"])
            self.assertLessEqual(row["price_from_kzt"], self.query.budget_kzt)
            self.assertNotIn(self.query.event_date.isoformat(), row["busy_dates"])

    def test_invalid_model_rank_is_entirely_rejected(self):
        profile = self.repository.contractors[0]
        base = {"candidates": [{"id": profile.id, "score": 70, "quote": profile.description[:60]}]}
        invalid = []
        for key, value in (("id", "unknown-id"), ("score", float("nan")), ("score", float("inf")),
                           ("score", True), ("score", 101), ("quote", "invented experience")):
            raw = copy.deepcopy(base)
            raw["candidates"][0][key] = value
            invalid.append(raw)
        invalid.extend(({"candidates": []}, {"candidates": base["candidates"] * 2}))
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_ranking(value, {profile.id: profile})

    def test_ai_failures_fall_back_and_do_not_reveal_error(self):
        def fail(*args):
            raise ValueError("secret-error-from-provider")
        service = AIService(AIConfig(api_key="unit-test-token"), transport=fail)
        result = recommend_with_ai(self.engine, self.query, service)
        self.assertEqual(result["results"], self.engine.recommend(self.query)["results"])
        self.assertFalse(result["ai"]["used"])
        self.assertNotIn("secret-error", json.dumps(result))

    def test_empty_market_does_not_call_model(self):
        def fail(*args):
            self.fail("Provider must not be called for an empty market")
        query = SearchQuery.from_dict(DEMO_CASES[3]["query"])
        result = recommend_with_ai(self.engine, query, AIService(AIConfig(api_key="unit-test-token"), transport=fail))
        self.assertEqual(result["status"], "no_market")
        self.assertFalse(result["ai"]["used"])


if __name__ == "__main__":
    unittest.main()
