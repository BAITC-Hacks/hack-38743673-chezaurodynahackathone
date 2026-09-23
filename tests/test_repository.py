from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from smartmatch.repository import ContractorRepository, CALENDAR_START, CALENDAR_END

ROOT = Path(__file__).resolve().parents[1]


class RepositoryValidationTests(unittest.TestCase):
    def setUp(self):
        with (ROOT / "data" / "contractors.csv").open(encoding="utf-8-sig", newline="") as handle:
            self.rows = list(csv.DictReader(handle))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def load(self, rows):
        path = Path(self.directory.name) / "catalog.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return ContractorRepository.from_csv(path)

    def test_nonfinite_and_nonpositive_max_hours_quarantined(self):
        for value in ("nan", "inf", "-inf", "0", "-1"):
            with self.subTest(value=value):
                repository = self.load([{**self.rows[0], "max_hours": value}, self.rows[1]])
                self.assertEqual(len(repository.contractors), 1)
                self.assertEqual(len(repository.quarantined), 1)

    def test_delimiter_only_required_collections_quarantined(self):
        for field in ("categories", "event_formats", "languages"):
            with self.subTest(field=field):
                repository = self.load([{**self.rows[0], field: " | | "}, self.rows[1]])
                self.assertEqual(len(repository.contractors), 1)
                self.assertEqual(len(repository.quarantined), 1)

    def test_duplicate_ids_quarantined_without_overwriting_first(self):
        repository = self.load([self.rows[0], {**self.rows[1], "id": self.rows[0]["id"]}])
        self.assertEqual(repository.contractors[0].name, self.rows[0]["anon_name"])
        self.assertEqual(repository.quarantined[0]["issues"], ["повторяющийся id"])

    def test_explicit_empty_calendar_is_valid_and_retains_coverage(self):
        repository = self.load([{**self.rows[0], "busy_dates": ""}])
        self.assertEqual(repository.contractors[0].busy_dates, frozenset())
        self.assertEqual(repository.metadata()["calendar"], {"min": CALENDAR_START.isoformat(), "max": CALENDAR_END.isoformat()})
        repository = self.load([{**self.rows[0], "busy_dates": "2026-10-15"}])
        self.assertEqual(repository.metadata()["calendar"]["min"], "2026-09-23")

    def test_absent_and_delimiter_only_calendar_is_not_a_free_calendar(self):
        for value in (None, " || "):
            row = {**self.rows[0], "busy_dates": value}
            self.assertTrue(ContractorRepository._critical_issues(row))

    def test_invalid_provenance_is_not_silently_false(self):
        for field in ("city_imputed", "price_imputed", "synthetic"):
            repository = self.load([{**self.rows[0], field: "unknown"}, self.rows[1]])
            self.assertEqual(len(repository.quarantined), 1)

    def test_list_duplicates_normalized_before_database_import(self):
        repository = self.load([{**self.rows[0], "languages": "Русский|русский| Русский "}])
        self.assertEqual(repository.contractors[0].languages, ("русский",))


if __name__ == "__main__":
    unittest.main()
