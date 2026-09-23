"""Проверки третьего этапа без сети и API-ключа."""

import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from profile_explanations import (
    DEFAULT_EXPLANATION_MODEL, ExplanationError, ExplanationProxyClient,
    explain_profiles, redact_text,
)
from smartmatch import rank_profiles


class ExplanationTests(unittest.TestCase):
    # Готовит три разные карточки второго этапа и ответ модели в обратном порядке.
    def setUp(self):
        self.order = {"preferences": "Спокойный стиль", "budget_kzt": 900000,
                      "language": "русский", "duration_hours": 6, "city": "Алматы"}
        self.selected = [
            {"profile": {"id": f"private-{i}", "anon_name": f"Кандидат-{i}",
                         "city": "Алматы", "phone": "+7 777 123 45 67",
                         "busy_dates": ["2026-10-15"], "description": "Деловые события.",
                         "price_from_kzt": 700000 + i * 50000, "max_hours": 8,
                         "languages": "русский|английский", "event_formats": "корпоратив",
                         "experience_years": 5 + i},
             "score": 90 - i, "penalties": {"text": i}}
            for i in range(3)
        ]
        self.answer = {"summaries": [
            {"index": i, "sentences": [f"Указан опыт {5 + i} лет.",
                                       "В описании отмечены деловые события."]}
            for i in reversed(range(3))
        ]}

    # Проверяет, что порядок ответа модели не изменяет исходные карточки и баллы.
    def test_preserves_all_cards_and_input(self):
        before = copy.deepcopy(self.selected)
        model = Mock()
        model.summarize.return_value = self.answer
        result = explain_profiles(self.order, self.selected, model)
        self.assertEqual(self.selected, before)
        self.assertEqual(len(result), 3)
        for i, item in enumerate(result):
            self.assertEqual(item["profile"], before[i]["profile"])
            self.assertEqual(item["score"], before[i]["score"])
            self.assertEqual(item["penalties"], before[i]["penalties"])
            self.assertEqual(len(item["explanation_sentences"]), 2)
            self.assertIn(f"{5 + i} лет", item["explanation"])
        model.summarize.assert_called_once()

    # Проверяет разрешённые данные и удаление известных личных сведений из текста.
    def test_compares_many_fields_without_identifying_data(self):
        self.order["preferences"] = "Алматы, встреча 2026-10-15"
        self.selected[0]["profile"]["description"] = "Кандидат-0, Алматы, +7 777 123 45 67. Опыт 5 лет."
        self.selected[0]["profile"]["unknown_private_field"] = "не передавать"
        model = Mock()
        model.summarize.return_value = self.answer
        explain_profiles(self.order, self.selected, model)
        task = model.summarize.call_args.args[0]
        serialized = json.dumps(task, ensure_ascii=False)
        for secret in ("Кандидат-0", "Алматы", "2026-10-15", "+7 777 123 45 67", "private-0", "не передавать"):
            self.assertNotIn(secret, serialized)
        facts = task["profiles"][0]["facts"]
        self.assertEqual(facts["price_from_kzt"], 700000)
        self.assertEqual(facts["max_hours"], 8)
        self.assertEqual(facts["experience_years"], 5)
        self.assertIn("languages", facts)
        self.assertIn("event_formats", facts)

    # Проверяет совместимость с реальным форматом результата второго этапа.
    def test_rank_then_explain(self):
        ranking_model = Mock()
        ranking_model.relevance.return_value = [0.6, 0.9, 0.8]
        selected = rank_profiles(self.order, [item["profile"] for item in self.selected], ranking_model)
        summary_model = Mock()
        summary_model.summarize.return_value = self.answer
        result = explain_profiles(self.order, selected, summary_model)
        self.assertEqual([r["profile"]["id"] for r in result], [r["profile"]["id"] for r in selected])

    # Проверяет неполную выдачу и отсутствие лишнего запроса при пустом входе.
    def test_partial_empty_and_oversized_input(self):
        model = Mock()
        self.assertEqual(explain_profiles(self.order, [], model), [])
        model.summarize.assert_not_called()
        model.summarize.return_value = {"summaries": [self.answer["summaries"][-1]]}
        self.assertEqual(len(explain_profiles(self.order, self.selected[:1], model)), 1)
        with self.assertRaises(ValueError):
            explain_profiles(self.order, self.selected + self.selected, model)

    # Проверяет запрет на пропуски, дубликаты и неверное число предложений.
    def test_rejects_invalid_or_partial_model_output(self):
        variants = [None, {"summaries": self.answer["summaries"][:2]},
                    {"summaries": [self.answer["summaries"][0]] * 3}]
        for sentences in (["Одно предложение."], ["Предложение."] * 4,
                          ["Два. В одном.", "Второе."], ["Без точки", "Второе."]):
            invalid = copy.deepcopy(self.answer)
            invalid["summaries"][0]["sentences"] = sentences
            variants.append(invalid)
        for variant in variants:
            with self.subTest(variant=variant):
                model = Mock()
                model.summarize.return_value = variant
                with self.assertRaises(ExplanationError):
                    explain_profiles(self.order, self.selected, model)

    # Проверяет отдельный выбор модели и ключа для третьего этапа.
    def test_environment_defaults_and_overrides(self):
        with patch.dict("os.environ", {"AI_PROXY_API_KEY": "test", "AI_PROXY_MODEL": "nano"}, clear=True):
            self.assertEqual(ExplanationProxyClient.from_env().model, DEFAULT_EXPLANATION_MODEL)
        with patch.dict("os.environ", {"AI_PROXY_API_KEY": "base", "EXPLANATION_PROXY_API_KEY": "separate",
                                       "EXPLANATION_PROXY_URL": "https://proxy.example/chat/completions",
                                       "EXPLANATION_PROXY_MODEL": "mini-custom"}, clear=True):
            client = ExplanationProxyClient.from_env()
            self.assertEqual(client.api_key, "separate")
            self.assertEqual(client.model, "mini-custom")
            self.assertEqual(client.url, "https://proxy.example/chat/completions")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ExplanationError):
                ExplanationProxyClient.from_env()

    # Проверяет, что очистка телефона не скрывает числовую характеристику цены.
    def test_redaction_preserves_price(self):
        text = "Цена от 10 000 000 тенге, телефон +7 777 123 45 67."
        cleaned = redact_text(text, [])
        self.assertIn("10 000 000", cleaned)
        self.assertNotIn("+7 777 123 45 67", cleaned)

    # Проверяет реальный HTTP-контракт с подменой сетевого ответа.
    def test_proxy_payload_and_response(self):
        reply = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self.answer)}}]}
        with patch("profile_explanations.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())) as send:
            result = explain_profiles(self.order, self.selected,
                                      ExplanationProxyClient("https://proxy.example/chat/completions", DEFAULT_EXPLANATION_MODEL, "test"))
        self.assertEqual(len(result), 3)
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(payload["model"], DEFAULT_EXPLANATION_MODEL)
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(len(json.loads(payload["messages"][1]["content"])["profiles"]), 3)

    # Проверяет, что сетевой сбой и отказ модели не создают частичную выдачу.
    def test_transport_errors(self):
        client = ExplanationProxyClient("https://proxy.example/chat/completions", "mini", "test")
        with patch("profile_explanations.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(ExplanationError):
                explain_profiles(self.order, self.selected, client)
        for reason in ("length", "content_filter"):
            reply = {"choices": [{"finish_reason": reason, "message": {"content": "{}"}}]}
            with patch("profile_explanations.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())):
                with self.assertRaises(ExplanationError):
                    explain_profiles(self.order, self.selected, client)


if __name__ == "__main__":
    unittest.main()
