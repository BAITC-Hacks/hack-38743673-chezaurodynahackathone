from __future__ import annotations

import csv
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

from smartmatch import ContractorRepository, RecommendationEngine, SearchQuery
from smartmatch.hard_filter import HardFilter


ROOT = Path(__file__).resolve().parents[1]


class RecommendationEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = ContractorRepository.from_csv(ROOT / "data" / "contractors.csv")
        cls.engine = RecommendationEngine(cls.repository)

    def dense_query(self, event_date: str = "2026-10-15") -> SearchQuery:
        return SearchQuery.from_dict({
            "city": "Алматы",
            "event_date": event_date,
            "event_format": "корпоратив",
            "category": "Ведущий",
            "budget_kzt": 1_500_000,
            "duration_hours": 6,
            "language": "русский",
            "preferences": "интеллигентный ведущий для бизнес-аудитории",
        })

    def test_catalog_shape_and_quality_gate(self) -> None:
        self.assertEqual(len(self.repository.contractors), 66)
        self.assertEqual(len(self.repository.quarantined), 0)

    def test_result_is_deterministic(self) -> None:
        query = self.dense_query()
        first = self.engine.recommend(query)
        second = self.engine.recommend(query)
        self.assertEqual(first, second)

    def test_hard_constraints_are_never_violated(self) -> None:
        query = self.dense_query()
        result = self.engine.recommend(query)
        by_id = {item.id: item for item in self.repository.contractors}
        for recommendation in result["results"]:
            item = by_id[recommendation["id"]]
            self.assertNotIn(query.event_date, item.busy_dates)
            self.assertLessEqual(item.price_from_kzt, query.budget_kzt)
            self.assertIn(query.event_format, item.event_formats)
            self.assertIn(query.language, item.languages)
            self.assertTrue(item.max_hours is None or item.max_hours >= query.duration_hours)

    def test_three_outcomes_are_explicit(self) -> None:
        success = self.engine.recommend(self.dense_query())
        self.assertEqual(success["status"], "success")

        no_market = self.engine.recommend(SearchQuery.from_dict({
            "city": "Зарубежье", "event_date": "2026-10-15", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 1_000_000,
        }))
        self.assertEqual(no_market["status"], "no_market")

        no_eligible = self.engine.recommend(SearchQuery.from_dict({
            "city": "Алматы", "event_date": "2026-12-31", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 1,
        }))
        self.assertEqual(no_eligible["status"], "no_eligible")

    def test_date_changes_availability_and_is_named_in_explanation(self) -> None:
        query = self.dense_query("2026-10-15")
        result = self.engine.recommend(query)
        self.assertTrue(all("15 октября" in item["explanation"] for item in result["results"]))
        busy_dates = sorted({day for item in self.repository.contractors for day in item.busy_dates})
        changed = any(
            [row["id"] for row in self.engine.recommend(self.dense_query(day.isoformat()))["results"]]
            != [row["id"] for row in result["results"]]
            for day in busy_dates
        )
        self.assertTrue(changed)

    def test_response_time_is_well_below_ten_seconds(self) -> None:
        start = time.perf_counter()
        for _ in range(100):
            self.engine.recommend(self.dense_query())
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 10)

    def test_missing_critical_data_is_quarantined(self) -> None:
        source = ROOT / "data" / "contractors.csv"
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            columns = list(rows[0])
        rows[0]["city"] = ""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            repository = ContractorRepository.from_csv(path)
        self.assertEqual(len(repository.contractors), 65)
        self.assertEqual(len(repository.quarantined), 1)
        self.assertIn("нет поля: город", repository.quarantined[0]["issues"])

    def test_hard_filter_returns_specific_rejection_reasons(self) -> None:
        query = SearchQuery.from_dict({
            "city": "Алматы", "event_date": "2026-12-31", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 100_000, "duration_hours": 12,
            "language": "казахский",
        })
        candidates = [
            item for item in self.repository.contractors
            if item.city == query.city and query.category in item.categories
        ]
        result = HardFilter.apply(candidates, query)
        self.assertFalse(result["accepted"])
        self.assertTrue(result["rejections"])
        self.assertEqual(len(result["rejections"]), len(candidates))
        self.assertTrue(any("дороже бюджета" in item.reasons for item in result["rejections"]))

    def test_invalid_price_and_calendar_are_quarantined(self) -> None:
        source = ROOT / "data" / "contractors.csv"
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            columns = list(rows[0])
        rows[0]["price_from_kzt"] = "0"
        rows[1]["busy_dates"] = "not-a-date"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            repository = ContractorRepository.from_csv(path)
        self.assertEqual(len(repository.contractors), 64)
        issues = [issue for row in repository.quarantined for issue in row["issues"]]
        self.assertIn("цена должна быть больше нуля", issues)
        self.assertIn("некорректная дата занятости", issues)


if __name__ == "__main__":
    unittest.main()

