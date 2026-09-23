"""Проверки импорта, целостности и использования каталога без внешних API."""

import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from generate_profiles import generate_profiles
from profile_database import (
    ROOT, database_stats, fetch_profiles, initialize_schema, insert_profiles,
    normalize_profile, open_database, read_csv_profiles,
)
from profile_explanations import explain_profiles
from smartmatch import rank_profiles


class ProfileDatabaseTests(unittest.TestCase):
    # Подготавливает отдельную базу для каждого теста, не меняя рабочий каталог.
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.addCleanup(self.connection.close)
        initialize_schema(self.connection)
        self.csv_profiles = read_csv_profiles(ROOT / "contractors.csv", "2026-09-23", "2026-12-31")

    # Проверяет сохранение всех полей и исходных признаков синтетических строк CSV.
    def test_import_and_full_round_trip(self):
        inserted = insert_profiles(self.connection, self.csv_profiles)
        self.assertEqual(inserted["inserted"], 66)
        rows = fetch_profiles(self.connection)
        self.assertEqual({p["id"]: p for p in rows}, {p["id"]: p for p in self.csv_profiles})
        self.assertEqual(database_stats(self.connection), {
            "total": 66, "original": 53, "csv_synthetic": 13, "generated": 0,
        })
        self.assertTrue(any(p["max_hours"] is None for p in rows))
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    # Проверяет воспроизводимость 30 новых профилей и отсутствие дубликатов при повторе.
    def test_generation_and_repeated_import(self):
        generated = generate_profiles(30)
        self.assertEqual(generated, generate_profiles(30))
        self.assertEqual(generate_profiles(10), generated[:10])
        self.assertEqual(len({p["id"] for p in generated}), 30)
        self.assertTrue(all(p["synthetic"] and p["source_type"] == "generated" for p in generated))
        profiles = [*self.csv_profiles, *generated]
        insert_profiles(self.connection, profiles)
        self.assertEqual(insert_profiles(self.connection, profiles), {"inserted": 0, "skipped": 96})
        self.assertEqual(database_stats(self.connection), {
            "total": 96, "original": 53, "csv_synthetic": 13, "generated": 30,
        })

    # Проверяет откат всей партии при конфликте ID без перезаписи существующего профиля.
    def test_conflict_rolls_back_entire_batch(self):
        insert_profiles(self.connection, self.csv_profiles)
        conflicting = copy.deepcopy(self.csv_profiles[0])
        conflicting["price_from_kzt"] += 1000
        with self.assertRaisesRegex(ValueError, "Конфликт ID"):
            insert_profiles(self.connection, [generate_profiles(1)[0], conflicting])
        self.assertEqual(database_stats(self.connection)["total"], 66)
        self.assertEqual(fetch_profiles(self.connection, [conflicting["id"]])[0], self.csv_profiles[0])

    # Проверяет внешние ключи и отклонение неизвестных ID вместо молчаливой потери записей.
    def test_relationships_and_missing_ids(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.connection:
                self.connection.execute("INSERT INTO profile_languages VALUES ('missing', 'русский')")
        with self.assertRaisesRegex(ValueError, "Не найдены"):
            fetch_profiles(self.connection, ["missing"])
        self.assertEqual(fetch_profiles(self.connection, []), [])

    # Проверяет, что некорректные данные не маскируются восстановленными значениями.
    def test_invalid_source_data_rejected(self):
        for field, value in (("city", ""), ("price_from_kzt", "nan"), ("synthetic", "maybe"),
                             ("max_hours", float("inf")), ("busy_dates", ["2027-01-01"])):
            with self.subTest(field=field):
                raw = {**self.csv_profiles[0], field: value}
                with self.assertRaises(ValueError):
                    normalize_profile(raw, source_type="csv", source_name="test.csv",
                                      calendar_start="2026-09-23", calendar_end="2026-12-31")

    # Проверяет закрытие и повторное открытие настоящего файла SQLite на диске.
    def test_database_persists_after_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.sqlite3"
            with open_database(path, create=True) as connection:
                initialize_schema(connection)
                insert_profiles(connection, self.csv_profiles)
            with open_database(path) as connection:
                self.assertEqual(database_stats(connection)["total"], 66)

    # Проверяет формат БД на входе второго и третьего этапов, не выполняя жёстких фильтров.
    def test_database_to_ranking_and_explanations_contract(self):
        insert_profiles(self.connection, self.csv_profiles)
        ids = [profile["id"] for profile in self.csv_profiles[:3]][::-1]
        rows = fetch_profiles(self.connection, ids)
        self.assertEqual([row["id"] for row in rows], ids)
        order = {"preferences": "сдержанный стиль", "budget_kzt": 1500000}
        scorer = Mock()
        scorer.relevance.return_value = [0.6, 0.8, 0.9]
        ranked = rank_profiles(order, rows, scorer)
        writer = Mock()
        writer.summarize.return_value = {"summaries": [
            {"index": i, "sentences": ["Цена указана в профиле.", "Условия требуют уточнения."]}
            for i in range(3)
        ]}
        explained = explain_profiles(order, ranked, writer)
        self.assertEqual([p["profile"]["id"] for p in explained], [p["profile"]["id"] for p in ranked])
        self.assertEqual(len(explained), 3)


if __name__ == "__main__":
    unittest.main()
