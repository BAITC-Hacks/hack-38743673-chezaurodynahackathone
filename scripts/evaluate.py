from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smartmatch import ContractorRepository, RecommendationEngine, SearchQuery  # noqa: E402
from smartmatch.web import DEMO_CASES  # noqa: E402


def main() -> None:
    repository = ContractorRepository.from_csv(ROOT / "data" / "contractors.csv")
    engine = RecommendationEngine(repository)
    by_id = {item.id: item for item in repository.contractors}
    cases = []

    for demo in DEMO_CASES:
        query = SearchQuery.from_dict(demo["query"])
        start = time.perf_counter()
        result = engine.recommend(query)
        elapsed_ms = (time.perf_counter() - start) * 1000
        hard_constraints_ok = all(
            query.event_date not in by_id[row["id"]].busy_dates
            and by_id[row["id"]].price_from_kzt <= query.budget_kzt
            and query.event_format in by_id[row["id"]].event_formats
            and (not query.language or query.language in by_id[row["id"]].languages)
            and (
                query.duration_hours is None
                or by_id[row["id"]].max_hours is None
                or by_id[row["id"]].max_hours >= query.duration_hours
            )
            for row in result["results"]
        )
        cases.append({
            "case": demo["name"],
            "status": result["status"],
            "result_ids": [row["id"] for row in result["results"]],
            "eligible_count": result["eligible_count"],
            "hard_constraints_ok": hard_constraints_ok,
            "elapsed_ms": round(elapsed_ms, 3),
        })

    query = SearchQuery.from_dict(DEMO_CASES[0]["query"])
    timings = []
    baseline = engine.recommend(query)
    deterministic = True
    for _ in range(100):
        start = time.perf_counter()
        current = engine.recommend(query)
        timings.append((time.perf_counter() - start) * 1000)
        deterministic = deterministic and current == baseline

    report = {
        "catalog": repository.metadata(),
        "demo_cases": cases,
        "deterministic_100_runs": deterministic,
        "latency_ms": {
            "median": round(statistics.median(timings), 3),
            "max": round(max(timings), 3),
        },
        "all_checks_passed": (
            deterministic
            and all(case["hard_constraints_ok"] for case in cases)
            and max(timings) < 10_000
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

