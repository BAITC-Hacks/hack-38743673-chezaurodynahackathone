from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import csv
from datetime import date
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from uuid import UUID

from smartmatch.database import Database
from smartmatch.generate_profiles import generate_profiles, DEFAULT_RULES
from smartmatch.repository import ContractorRepository

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "contractors.csv"


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "nested" / "catalog.sqlite3"
        self.database = Database(self.path)
        self.repository = self.database.initialize(CSV)
        self.first_id, self.other_id = [item.id for item in self.repository.contractors[:2]]

    def result(self):
        return {"status": "success", "results": [{"id": self.first_id, "score": 80, "explanation": "Факт из профиля"}]}

    def test_round_trip_preserves_all_source_fields_and_flags(self):
        original = ContractorRepository.from_csv(CSV)
        self.assertEqual(self.repository.contractors, original.contractors)
        self.assertEqual(self.repository.metadata(), original.metadata())
        self.assertEqual(self.database.stats(), {"profiles": 66, "searches": 0, "selections": 0, "generated_count": 0, "quarantined_count": 0})
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM profiles WHERE source_type='csv' AND synthetic=0").fetchone()[0], 53)

    def test_reopening_does_not_reseed_or_require_original_csv(self):
        search_id = self.database.record_search({"preferences": "сдержанный стиль"}, self.result())
        reopened = Database(self.path)
        reopened.initialize(Path(self.directory.name) / "no-longer-available.csv")
        self.assertEqual(reopened.stats()["profiles"], 66)
        self.assertEqual(reopened.export_history()[0]["search_id"], search_id)

    def test_concurrent_initialization_seeds_once(self):
        path = Path(self.directory.name) / "simultaneous.sqlite3"
        def initialize(_):
            return len(Database(path).initialize(CSV).contractors)
        with ThreadPoolExecutor(max_workers=6) as pool:
            counts = list(pool.map(initialize, range(6)))
        self.assertEqual(counts, [66] * 6)
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM import_audit").fetchone()[0], 1)

    def test_idempotent_selection_requires_returned_candidate_and_survives_restart(self):
        search_id = self.database.record_search({}, self.result())
        self.assertEqual(str(UUID(search_id)), search_id)
        self.assertTrue(self.database.record_selection(search_id, self.first_id))
        self.assertFalse(self.database.record_selection(search_id, self.first_id))
        for invalid_search, invalid_profile in ((search_id, self.other_id), ("unknown", self.first_id), (search_id, "unknown")):
            with self.assertRaises(ValueError):
                self.database.record_selection(invalid_search, invalid_profile)
        self.assertEqual(Database(self.path).stats()["selections"], 1)

    def test_query_allowlist_excludes_credentials_and_serializes_date(self):
        query = {"event_date": date(2026, 10, 15), "preferences": "деловой стиль", "OPENAI_API_KEY": "should-not-be-saved",
                 "include_synthetic": False, "sort_by": "price_asc", "min_budget_kzt": 100000, "use_ai": False}
        self.database.record_search(query, self.result())
        exported = self.database.export_history()[0]
        self.assertEqual(exported["query"]["event_date"], "2026-10-15")
        self.assertNotIn("OPENAI_API_KEY", exported["query"])
        self.assertNotIn("should-not-be-saved", json.dumps(exported))
        self.assertEqual(exported["result"], self.result())
        self.assertFalse(exported["query"]["include_synthetic"])

    def test_unknown_duplicate_and_nonfinite_results_do_not_create_partial_search(self):
        for result in ({"results": [{"id": "unknown"}]}, {"results": [{"id": self.first_id}, {"id": self.first_id}]},
                       {"results": [{"id": self.first_id, "score": float("nan")}]}, {"results": [None]}):
            with self.assertRaises(ValueError):
                self.database.record_search({}, result)
        self.assertEqual(self.database.stats()["searches"], 0)

    def test_empty_results_are_collected_but_cannot_be_selected(self):
        search_id = self.database.record_search({}, {"status": "no_eligible", "results": []})
        self.assertEqual(self.database.stats()["searches"], 1)
        with self.assertRaises(ValueError):
            self.database.record_selection(search_id, self.first_id)

    def test_concurrent_requests_use_independent_connections(self):
        def save(index):
            search_id = self.database.record_search({"preferences": f"запрос {index}"}, self.result())
            self.database.record_selection(search_id, self.first_id)
            return search_id
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(save, range(24)))
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(self.database.stats()["searches"], 24)
        self.assertEqual(self.database.stats()["selections"], 24)

    def test_generation_is_reproducible_opt_in_and_idempotent(self):
        first = generate_profiles(30)
        self.assertEqual(first, generate_profiles(30))
        self.assertEqual(first[:10], generate_profiles(10))
        self.assertTrue(all(row["contractor"].synthetic for row in first))
        self.assertEqual(self.database.add_generated(30), {"inserted": 30, "skipped": 0})
        self.assertEqual(self.database.add_generated(30), {"inserted": 0, "skipped": 30})
        self.assertEqual(self.database.stats()["profiles"], 96)
        self.assertEqual(self.database.stats()["generated_count"], 30)

    def test_generation_conflict_is_rejected_without_overwrite(self):
        self.database.add_generated(1)
        rules = json.loads(DEFAULT_RULES.read_text(encoding="utf-8-sig"))
        rules["cities"] = ["Изменённый город"]
        path = Path(self.directory.name) / "different-rules.json"
        path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Конфликт ID"):
            self.database.add_generated(30, path)
        self.assertEqual(self.database.stats()["profiles"], 67)

    def test_csv_quality_audit_persists_after_restart(self):
        with CSV.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["city"] = ""
        path = Path(self.directory.name) / "invalid-row.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        database = Database(Path(self.directory.name) / "quality.sqlite3")
        database.initialize(path)
        self.assertEqual(database.stats()["profiles"], 65)
        self.assertEqual(database.stats()["quarantined_count"], 1)
        self.assertIn("нет поля: город", Database(database.path).repository().quarantined[0]["issues"])

    def test_export_cli_writes_local_json_and_refuses_overwrite(self):
        self.database.record_search({"preferences": "пример"}, self.result())
        output = Path(self.directory.name) / "exports" / "history.json"
        command = [sys.executable, str(ROOT / "scripts" / "export_history.py"), "--db", str(self.path), "--output", str(output)]
        first = subprocess.run(command, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))), 1)
        second = subprocess.run(command, capture_output=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))), 1)

    def test_init_cli_default_does_not_generate_extra_profiles(self):
        path = Path(self.directory.name) / "cli.sqlite3"
        completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "init_database.py"), "--db", str(path)], capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(json.loads(completed.stdout)["profiles"], 66)


if __name__ == "__main__":
    unittest.main()
