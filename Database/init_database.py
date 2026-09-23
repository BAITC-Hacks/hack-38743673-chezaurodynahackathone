"""Создаёт SQLite-каталог, импортирует CSV и добавляет синтетические тестовые профили."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from generate_profiles import DEFAULT_RULES, generate_profiles
from profile_database import (
    DEFAULT_DATABASE, ROOT, database_stats, initialize_schema, insert_profiles,
    open_database, read_csv_profiles,
)


# -----------------------------------------------------------------------------
# Запуск: сначала проверяет все входные данные, затем записывает каталог транзакцией.
# -----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--csv", type=Path, default=ROOT / "contractors.csv")
    parser.add_argument("--generate", type=int, default=30, help="Количество дополнительных тестовых профилей")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="JSON-файл правил генерации")
    parser.add_argument("--calendar-start", default="2026-09-23", help="Начало покрытия календаря CSV")
    parser.add_argument("--calendar-end", default="2026-12-31", help="Конец покрытия календаря CSV")
    args = parser.parse_args()
    if args.generate < 0:
        parser.error("--generate не может быть отрицательным")
    try:
        original = read_csv_profiles(args.csv, args.calendar_start, args.calendar_end)
        generated = generate_profiles(args.generate, args.rules) if args.generate else []
        with open_database(args.db, create=True) as connection:
            initialize_schema(connection)
            changes = insert_profiles(connection, [*original, *generated])
            result = {"database": str(args.db.resolve()), **changes, **database_stats(connection)}
            result["integrity"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if connection.execute("PRAGMA foreign_key_check").fetchall() or result["integrity"] != "ok":
                raise ValueError("Проверка целостности БД не пройдена")
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.error(str(error))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
