"""Демонстрация этапа 3: без аргументов — заглушка, --live — один вызов API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from profile_explanations import ExplanationError, explain_profiles


# -----------------------------------------------------------------------------
# Демонстрационная модель: показывает формат ответа без ключа и сетевого запроса.
# -----------------------------------------------------------------------------
class DemoExplanationModel:
    def summarize(self, comparison):
        return {"summaries": [
            {"index": i, "sentences": [
                f"Указанная начальная цена составляет {item['facts']['price_from_kzt']} тенге.",
                f"Максимальная длительность работы составляет {item['facts']['max_hours']} часов.",
            ]}
            for i, item in enumerate(comparison["profiles"])
        ]}


# -----------------------------------------------------------------------------
# Запуск: читает готовые три карточки и проверяет их дополнение краткими текстами.
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Один реальный платный запрос к настроенному прокси")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    fixture = Path(__file__).parent / "examples" / "selected_profiles.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    try:
        result = explain_profiles(
            data["request"], data["selected_profiles"],
            model=None if args.live else DemoExplanationModel(),
        )
    except (ExplanationError, ValueError) as error:
        parser.exit(1, f"Ошибка третьего этапа: {error}\n")
    print(json.dumps({"mode": "live" if args.live else "demo", "profiles": result},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
