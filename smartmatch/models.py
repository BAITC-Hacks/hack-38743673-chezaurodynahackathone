from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Contractor:
    id: str
    name: str
    categories: tuple[str, ...]
    city: str
    city_imputed: bool
    synthetic: bool
    price_from_kzt: int
    price_imputed: bool
    event_formats: tuple[str, ...]
    languages: tuple[str, ...]
    max_hours: float | None
    busy_dates: frozenset[date]
    description: str


@dataclass(frozen=True, slots=True)
class SearchQuery:
    city: str
    event_date: date
    event_format: str
    category: str
    budget_kzt: int
    duration_hours: float | None = None
    language: str | None = None
    preferences: str = ""

    @classmethod
    def from_dict(cls, value: dict) -> "SearchQuery":
        required = ("city", "event_date", "event_format", "category", "budget_kzt")
        missing = [key for key in required if value.get(key) in (None, "")]
        if missing:
            raise ValueError(f"Не заполнены обязательные поля: {', '.join(missing)}")

        try:
            event_date = date.fromisoformat(str(value["event_date"]))
        except ValueError as exc:
            raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД") from exc

        try:
            budget = int(value["budget_kzt"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Бюджет должен быть целым числом") from exc
        if budget <= 0:
            raise ValueError("Бюджет должен быть больше нуля")

        duration_raw = value.get("duration_hours")
        duration = None
        if duration_raw not in (None, ""):
            try:
                duration = float(duration_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("Длительность должна быть числом") from exc
            if duration <= 0:
                raise ValueError("Длительность должна быть больше нуля")

        language = str(value.get("language") or "").strip().lower() or None
        return cls(
            city=str(value["city"]).strip(),
            event_date=event_date,
            event_format=str(value["event_format"]).strip().lower(),
            category=str(value["category"]).strip(),
            budget_kzt=budget,
            duration_hours=duration,
            language=language,
            preferences=str(value.get("preferences") or "").strip(),
        )

