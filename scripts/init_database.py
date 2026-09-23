"""Initialize the persistent catalog. Test profiles are explicit opt-in."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smartmatch.database import Database, DEFAULT_DATABASE
from smartmatch.generate_profiles import DEFAULT_RULES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--csv", type=Path, default=ROOT / "data" / "contractors.csv")
    parser.add_argument("--generate", type=int, default=0, help="Add explicit synthetic samples; default 0")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    args = parser.parse_args()
    if not 0 <= args.generate <= 10000:
        parser.error("--generate должен быть от 0 до 10000")
    try:
        database = Database(args.db)
        database.initialize(args.csv)
        changes = database.add_generated(args.generate, args.rules) if args.generate else {"inserted": 0, "skipped": 0}
        result = {"database": str(database.path), **database.stats(), "generated_changes": changes}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.error(str(error))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
