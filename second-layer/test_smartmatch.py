"""Проверки ранжирования уже отфильтрованных строк из БД."""

import io
import json
import sqlite3
import unittest
from unittest.mock import patch

from smartmatch import (
    DEFAULT_RANKING_MODEL,
    OPENAI_CHAT_COMPLETIONS_URL,
    AIProxyClient,
    rank_profiles,
)


class FakeModel:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def relevance(self, preferences, descriptions):
        self.calls.append((preferences, list(descriptions)))
        return self.scores


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "preferences": "спокойный ведущий",
            "budget_kzt": 100_000,
            "language": "русский",
            "duration_hours": 6,
            "category": "Ведущий",
            "event_date": "2026-10-15",
        }

    def row(self, **changes):
        profile = {
            "id": "A", "anon_name": "Имя", "description": "Спокойно веду события.",
            "price_from_kzt": 70_000, "languages": "русский|казахский",
            "max_hours": 8, "synthetic": False, "city_imputed": False,
            "price_imputed": False, "categories": "Ведущий", "busy_dates": "",
        }
        profile.update(changes)
        return profile

    # Проверяет, что модель оценивает только описания и меняет порядок кандидатов.
    def test_model_relevance_affects_top_three(self):
        rows = [self.row(id=str(index), description=f"Описание {index}") for index in range(4)]
        model = FakeModel([0.1, 0.9, 0.5, 0.7])
        result = rank_profiles(self.request, rows, model)
        self.assertEqual([item["profile"]["id"] for item in result], ["1", "3", "2"])
        self.assertEqual(model.calls, [("спокойный ведущий", [f"Описание {i}" for i in range(4)])])
        self.assertEqual(result[0]["penalties"]["text"], 3.4)

    # Проверяет правило вычитания баллов без дополнительной фильтрации строк.
    def test_mismatches_subtract_points_but_keep_profiles(self):
        rows = [
            self.row(id="perfect"),
            self.row(id="expensive", price_from_kzt=100_000),
            self.row(id="language", languages="казахский"),
            self.row(id="duration", max_hours=3),
        ]
        result = rank_profiles(self.request, rows, FakeModel([1.0] * 4))
        self.assertEqual([item["profile"]["id"] for item in result], ["perfect", "duration", "language"])
        self.assertEqual(result[0]["score"], 100.0)
        self.assertEqual(result[1]["penalties"]["duration"], 5.0)
        self.assertEqual(result[2]["penalties"]["language"], 12.0)

    # Проверяет, что категория, дата, имя и ID не участвуют в баллах и разрешении ничьей.
    def test_excluded_fields_do_not_affect_ranking(self):
        rows = [
            self.row(id="Z", anon_name="Я", categories="Другое", busy_dates="2026-10-15"),
            self.row(id="A", anon_name="А", categories="Ведущий", busy_dates=""),
            self.row(id="M", anon_name="М", categories="Другое", busy_dates="2026-12-01"),
        ]
        result = rank_profiles(self.request, rows, FakeModel([1.0, 1.0, 1.0]))
        self.assertEqual([item["profile"]["id"] for item in result], ["Z", "A", "M"])
        self.assertEqual({item["score"] for item in result}, {100.0})

    # Проверяет прямой приём sqlite3.Row без загрузчика CSV или SQL-фильтра внутри модуля.
    def test_accepts_database_rows(self):
        database = sqlite3.connect(":memory:")
        database.row_factory = sqlite3.Row
        database.execute("CREATE TABLE candidates (id TEXT, description TEXT, price_from_kzt INTEGER, languages TEXT, max_hours REAL)")
        database.execute("INSERT INTO candidates VALUES ('X', 'Ведущий', 70000, 'русский', 8)")
        rows = database.execute("SELECT * FROM candidates")
        result = rank_profiles(self.request, rows, FakeModel([1.0]))
        self.assertEqual(result[0]["profile"]["id"], "X")
        database.close()

    # Проверяет полный текстовый штраф за пустое описание даже при ошибочной оценке модели.
    def test_empty_description_gets_full_text_penalty(self):
        result = rank_profiles(self.request, [self.row(description="")], FakeModel([1.0]))
        self.assertEqual(result[0]["penalties"]["text"], 34.0)
        self.assertEqual(result[0]["score"], 66.0)

    # Проверяет готовое OpenAI-подключение: нужен только ключ в окружении сервера.
    def test_openai_defaults_are_used_from_environment(self):
        with patch.dict("os.environ", {"AI_PROXY_API_KEY": "test-key"}, clear=True):
            client = AIProxyClient.from_env()
        self.assertEqual(client.url, OPENAI_CHAT_COMPLETIONS_URL)
        self.assertEqual(client.model, DEFAULT_RANKING_MODEL)
        self.assertEqual(client.api_key, "test-key")

    # Проверяет формат вызова прокси и то, что метаданные не уходят модели.
    def test_proxy_request_contains_only_preference_and_descriptions(self):
        reply = {"choices": [{"message": {"content": json.dumps({"scores": [
            {"index": 1, "relevance": 0.8}, {"index": 0, "relevance": 0.2},
        ]})}}]}
        with patch("smartmatch.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())) as send:
            scores = AIProxyClient("https://proxy.example/chat/completions", "small", "secret").relevance(
                "спокойный ведущий", ["Первое описание", "Второе описание"]
            )
        self.assertEqual(scores, [0.2, 0.8])
        sent = json.loads(send.call_args.args[0].data)
        task = json.loads(sent["messages"][1]["content"])
        self.assertEqual(set(task), {"preferences", "profiles"})
        self.assertEqual(set(task["profiles"][0]), {"index", "description"})
        self.assertEqual(send.call_args.args[0].get_header("Authorization"), "Bearer secret")

    # Проверяет, что неполный ответ модели не даёт непредсказуемый рейтинг.
    def test_proxy_rejects_missing_score(self):
        reply = {"choices": [{"message": {"content": json.dumps({"scores": [
            {"index": 0, "relevance": 0.8},
        ]})}}]}
        with patch("smartmatch.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(reply).encode())):
            with self.assertRaisesRegex(RuntimeError, "некорректные оценки"):
                AIProxyClient("https://proxy.example/chat/completions", "small").relevance("текст", ["a", "b"])


if __name__ == "__main__":
    unittest.main()
