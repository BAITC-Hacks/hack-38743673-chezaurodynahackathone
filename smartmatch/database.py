"""Persistent catalog and local MVP activity, using short-lived SQLite connections."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .models import Contractor
from .repository import CALENDAR_END, CALENDAR_START, ContractorRepository


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "runtime" / "smartmatch.sqlite3"
QUERY_FIELDS = frozenset({
    "city", "event_date", "event_format", "category", "budget_kzt", "min_budget_kzt",
    "duration_hours", "language", "preferences", "include_synthetic", "sort_by", "use_ai",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value) -> str:
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"Значение {type(item).__name__} нельзя сохранить в JSON")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=encode)


class Database:
    """A file-backed database; no connection is shared between HTTP threads."""

    def __init__(self, path: str | Path = DEFAULT_DATABASE) -> None:
        if str(path) == ":memory:":
            raise ValueError("Для постоянной БД нужен путь к файлу, не :memory:")
        self.path = Path(path).resolve()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, csv_path: str | Path = ROOT / "data" / "contractors.csv") -> ContractorRepository:
        """Create schema and seed once. Subsequent starts never overwrite catalog/history."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            connection.execute("BEGIN IMMEDIATE")
            seeded = connection.execute("SELECT value FROM metadata WHERE key = 'seeded'").fetchone()
            if seeded is None:
                if connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 0:
                    repository = ContractorRepository.from_csv(csv_path)
                    source_name = Path(csv_path).name
                    for item in repository.contractors:
                        self._insert_profile(connection, item, "csv", source_name)
                    connection.execute(
                        "INSERT INTO import_audit(imported_at,source_name,accepted_count,quarantined_json) VALUES (?,?,?,?)",
                        (_now(), source_name, len(repository.contractors), _json(repository.quarantined)),
                    )
                connection.execute("INSERT INTO metadata(key,value) VALUES ('seeded', ?)", (_now(),))
                connection.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES ('schema_version', '1')")
        return self.repository()

    @staticmethod
    def _insert_profile(connection, item: Contractor, source_type: str, source_name: str,
                        experience_years: int | None = None) -> None:
        connection.execute(
            """INSERT INTO profiles(id,anon_name,city,city_imputed,synthetic,price_from_kzt,
            price_imputed,max_hours,description,experience_years,calendar_start,calendar_end,source_type,source_name)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item.id, item.name, item.city, item.city_imputed, item.synthetic, item.price_from_kzt,
             item.price_imputed, item.max_hours, item.description, experience_years,
             CALENDAR_START.isoformat(), CALENDAR_END.isoformat(), source_type, source_name),
        )
        for table, column, values in (
            ("profile_categories", "category", item.categories),
            ("profile_event_formats", "event_format", item.event_formats),
            ("profile_languages", "language", item.languages),
        ):
            connection.executemany(
                f"INSERT INTO {table}(profile_id,{column},position) VALUES (?,?,?)",
                ((item.id, value, index) for index, value in enumerate(values)),
            )
        connection.executemany("INSERT INTO profile_busy_dates VALUES (?,?)",
                               ((item.id, value.isoformat()) for value in sorted(item.busy_dates)))

    def repository(self) -> ContractorRepository:
        with self._connection() as connection:
            connection.execute("BEGIN")
            rows = connection.execute("SELECT * FROM profiles ORDER BY rowid").fetchall()
            collections: dict[str, dict[str, list[str]]] = {}
            for name, column in (("categories", "category"), ("event_formats", "event_format"),
                                 ("languages", "language"), ("busy_dates", "busy_date")):
                grouped: dict[str, list[str]] = {}
                ordering = "busy_date" if name == "busy_dates" else "position"
                for row in connection.execute(f"SELECT profile_id,{column} FROM profile_{name} ORDER BY {ordering}"):
                    grouped.setdefault(row["profile_id"], []).append(row[column])
                collections[name] = grouped
            quarantined = []
            for row in connection.execute("SELECT quarantined_json FROM import_audit ORDER BY id"):
                quarantined.extend(json.loads(row[0]))
            contractors = tuple(Contractor(
                id=row["id"], name=row["anon_name"], city=row["city"],
                city_imputed=bool(row["city_imputed"]), synthetic=bool(row["synthetic"]),
                price_from_kzt=row["price_from_kzt"], price_imputed=bool(row["price_imputed"]),
                max_hours=row["max_hours"], description=row["description"],
                categories=tuple(collections["categories"].get(row["id"], [])),
                event_formats=tuple(collections["event_formats"].get(row["id"], [])),
                languages=tuple(collections["languages"].get(row["id"], [])),
                busy_dates=frozenset(date.fromisoformat(value) for value in collections["busy_dates"].get(row["id"], [])),
            ) for row in rows)
        return ContractorRepository(contractors, tuple(quarantined))

    def add_generated(self, count: int = 30, rules_path: str | Path | None = None) -> dict[str, int]:
        """Explicit opt-in sample generation; repeats skip identical IDs, conflicts roll back."""
        from .generate_profiles import DEFAULT_RULES, generate_profiles
        records = generate_profiles(count, Path(rules_path) if rules_path else DEFAULT_RULES)
        inserted = skipped = 0
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {item.id: item for item in self.repository().contractors}
            for record in records:
                item = record["contractor"]
                if item.id in existing:
                    if existing[item.id] != item:
                        raise ValueError(f"Конфликт ID: {item.id}; существующий профиль не перезаписан")
                    skipped += 1
                    continue
                self._insert_profile(connection, item, "generated", record["source_name"], record["experience_years"])
                inserted += 1
        return {"inserted": inserted, "skipped": skipped}

    def record_search(self, query: dict, result: dict) -> str:
        if not isinstance(query, dict) or not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise ValueError("Некорректный запрос или результат поиска")
        ids = [item.get("id") if isinstance(item, dict) else None for item in result["results"]]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("У результата должны быть уникальные ID подрядчиков")
        search_id = str(uuid4())
        query_json = _json({key: value for key, value in query.items() if key in QUERY_FIELDS})
        result_json = _json(result)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            known_ids = {row[0] for row in connection.execute("SELECT id FROM profiles")}
            if not set(ids).issubset(known_ids):
                raise ValueError("В результатах найден неизвестный подрядчик")
            connection.execute("INSERT INTO searches VALUES (?,?,?,?)", (search_id, _now(), query_json, result_json))
            connection.executemany("INSERT INTO search_results VALUES (?,?,?)",
                                   ((search_id, value, index) for index, value in enumerate(ids, 1)))
        return search_id

    def record_selection(self, search_id: str, contractor_id: str) -> bool:
        if not isinstance(search_id, str) or not isinstance(contractor_id, str):
            raise ValueError("Нужны ID поиска и подрядчика")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            found = connection.execute(
                "SELECT 1 FROM search_results WHERE search_id=? AND contractor_id=?", (search_id, contractor_id)
            ).fetchone()
            if found is None:
                raise ValueError("Подрядчик отсутствует в результатах этого поиска")
            cursor = connection.execute("INSERT OR IGNORE INTO selections VALUES (?,?,?)", (search_id, contractor_id, _now()))
            return cursor.rowcount == 1

    def stats(self) -> dict[str, int]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("profiles", "searches", "selections")}
            counts["generated_count"] = connection.execute("SELECT COUNT(*) FROM profiles WHERE source_type='generated'").fetchone()[0]
            counts["quarantined_count"] = sum(len(json.loads(row[0])) for row in connection.execute("SELECT quarantined_json FROM import_audit"))
        return counts

    def export_history(self) -> list[dict]:
        """Local operator export; deliberately not exposed as an HTTP route."""
        with self._connection() as connection:
            connection.execute("BEGIN")
            selections: dict[str, list[dict]] = {}
            for row in connection.execute("SELECT * FROM selections ORDER BY created_at,contractor_id"):
                selections.setdefault(row["search_id"], []).append({
                    "contractor_id": row["contractor_id"], "created_at": row["created_at"],
                })
            return [{"search_id": row["id"], "created_at": row["created_at"],
                     "query": json.loads(row["query_json"]), "result": json.loads(row["result_json"]),
                     "selections": selections.get(row["id"], [])}
                    for row in connection.execute("SELECT * FROM searches ORDER BY created_at,id")]
