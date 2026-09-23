"""Export local search/selection history as UTF-8 JSON, without an HTTP endpoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smartmatch.database import Database, DEFAULT_DATABASE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=ROOT / "exports" / "history.json")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error("База данных не найдена; сначала запустите сервер или init_database.py")
    if args.output.resolve() == args.db.resolve():
        parser.error("Нельзя перезаписать базу данных файлом экспорта")
    try:
        records = Database(args.db).export_history()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Avoid accidentally replacing a previous operator export.
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Сохранено поисков: {len(records)}. Файл: {args.output.resolve()}")


if __name__ == "__main__":
    main()
