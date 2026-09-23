from __future__ import annotations

import csv
import tempfile
import time
import unittest
from dataclasses import replace
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

    def fixture_profile(self, identifier="base"):
        return replace(self.repository.contractors[0], id=identifier, city="Алматы", categories=("Ведущий",),
                       event_formats=("корпоратив",), languages=("русский",), max_hours=8,
                       price_from_kzt=500_000, synthetic=False, city_imputed=False, price_imputed=False,
                       busy_dates=frozenset({date(2026, 9, 23), date(2026, 12, 31)}))

    def test_all_filters_work_together_before_top_three(self):
        base = self.fixture_profile()
        profiles = [base,
                    replace(base, id="wrong-city", city="Астана"),
                    replace(base, id="wrong-category", categories=("Флорист",)),
                    replace(base, id="busy", busy_dates=base.busy_dates | {date(2026, 10, 15)}),
                    replace(base, id="too-cheap", price_from_kzt=99_999),
                    replace(base, id="too-expensive", price_from_kzt=1_500_001),
                    replace(base, id="wrong-format", event_formats=("свадьба",)),
                    replace(base, id="wrong-language", languages=("английский",)),
                    replace(base, id="too-short", max_hours=5),
                    replace(base, id="synthetic", synthetic=True)]
        engine = RecommendationEngine(ContractorRepository(tuple(profiles)))
        query = replace(self.dense_query(), min_budget_kzt=100_000, include_synthetic=False)
        result = engine.recommend(query)
        self.assertEqual([row["id"] for row in result["results"]], ["base"])
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["market_count"], 8)
        rejected = {row["id"] for row in result["rejected_candidates"]}
        self.assertEqual(rejected, {"busy", "too-cheap", "too-expensive", "wrong-format", "wrong-language", "too-short", "synthetic"})

    def test_price_sort_applies_to_entire_eligible_pool_and_ties_use_id(self):
        base = self.fixture_profile()
        profiles = tuple(replace(base, id=identifier, price_from_kzt=price) for identifier, price in
                         (("e", 800_000), ("b", 400_000), ("a", 400_000), ("d", 700_000), ("c", 500_000)))
        engine = RecommendationEngine(ContractorRepository(profiles))
        for mode, expected in (("price_asc", ["a", "b", "c"]), ("price_desc", ["e", "d", "c"])):
            with self.subTest(mode=mode):
                result = engine.recommend(replace(self.dense_query(), sort_by=mode))
                self.assertEqual([row["id"] for row in result["results"]], expected)
                self.assertEqual(result["sort_by"], mode)
        tied = RecommendationEngine(ContractorRepository((replace(base, id="z"), replace(base, id="a"))))
        self.assertEqual([row["id"] for row in tied.recommend(self.dense_query())["results"]], ["a", "z"])

    def test_price_boundaries_are_inclusive_and_synthetic_is_optional(self):
        base = self.fixture_profile()
        engine = RecommendationEngine(ContractorRepository((base, replace(base, id="synthetic", synthetic=True))))
        query = replace(self.dense_query(), min_budget_kzt=500_000, budget_kzt=500_000)
        self.assertEqual(engine.recommend(query)["eligible_count"], 2)
        self.assertEqual(engine.recommend(replace(query, include_synthetic=False))["eligible_count"], 1)

    def test_query_validation_and_normalization_are_shared_with_direct_callers(self):
        payload = {"city": "  Алматы  ", "event_date": " 2026-10-15 ", "event_format": " КОРПОРАТИВ ",
                   "category": " Ведущий ", "budget_kzt": "500000", "language": " РУССКИЙ ",
                   "min_budget_kzt": 100_000, "sort_by": "price_asc", "include_synthetic": False}
        query = SearchQuery.from_dict(payload)
        self.assertEqual((query.city, query.event_format, query.category, query.language),
                         ("Алматы", "корпоратив", "Ведущий", "русский"))
        for field, value in (("city", "  "), ("category", []), ("language", ["русский"]),
                             ("budget_kzt", True), ("budget_kzt", 12.5), ("min_budget_kzt", -1),
                             ("min_budget_kzt", 500_001), ("min_budget_kzt", float("nan")),
                             ("include_synthetic", "false"), ("sort_by", "random"),
                             ("event_date", "20261015"), ("preferences", []), ("duration_hours", True)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                SearchQuery.from_dict({**payload, field: value})


if __name__ == "__main__":
    unittest.main()
