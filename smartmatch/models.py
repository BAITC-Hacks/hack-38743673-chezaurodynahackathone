from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math


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


def _text(value: object, label: str, *, required: bool = False, maximum: int = 120) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Поле {label} должно быть строкой")
    value = " ".join(value.split())
    if required and not value:
        raise ValueError(f"Не заполнено поле {label}")
    if len(value) > maximum:
        raise ValueError(f"Поле {label} слишком длинное")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError()
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            raise ValueError()
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Поле {label} должно быть целым числом") from None
    if not minimum <= result <= 1_000_000_000:
        raise ValueError(f"Поле {label} должно быть от {minimum} до 1 000 000 000 ₸")
    return result


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
    min_budget_kzt: int = 0
    include_synthetic: bool = True
    sort_by: str = "relevance"

    @classmethod
    def from_dict(cls, value: dict) -> "SearchQuery":
        if not isinstance(value, dict):
            raise ValueError("Запрос должен быть объектом JSON")
        required = ("city", "event_date", "event_format", "category", "budget_kzt")
        missing = [key for key in required if value.get(key) in (None, "")]
        if missing:
            raise ValueError(f"Не заполнены обязательные поля: {', '.join(missing)}")

        city = _text(value["city"], "city", required=True)
        category = _text(value["category"], "category", required=True)
        event_format = _text(value["event_format"], "event_format", required=True).casefold()
        date_text = _text(value["event_date"], "event_date", required=True)
        try:
            event_date = date.fromisoformat(date_text)
            if event_date.isoformat() != date_text:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("Дата должна быть в формате ГГГГ-ММ-ДД") from exc

        budget = _integer(value["budget_kzt"], "budget_kzt", 1)
        minimum = _integer(value.get("min_budget_kzt", 0), "min_budget_kzt")
        if minimum > budget:
            raise ValueError("Нижняя граница цены не должна превышать бюджет")

        duration_raw = value.get("duration_hours")
        duration = None
        if duration_raw not in (None, ""):
            try:
                duration = float(duration_raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Длительность должна быть числом") from exc
            if isinstance(duration_raw, bool) or not math.isfinite(duration) or not 0 < duration <= 24:
                raise ValueError("Длительность должна быть больше нуля и не больше 24 часов")

        language = _text(value.get("language"), "language").casefold() or None
        preferences = _text(value.get("preferences"), "preferences", maximum=6000)
        include_synthetic = value.get("include_synthetic", True)
        if not isinstance(include_synthetic, bool):
            raise ValueError("Поле include_synthetic должно быть логическим значением")
        sort_by = _text(value.get("sort_by", "relevance"), "sort_by", required=True).casefold()
        if sort_by not in {"relevance", "price_asc", "price_desc"}:
            raise ValueError("Неизвестный порядок сортировки")
        return cls(city=city, event_date=event_date, event_format=event_format, category=category,
                   budget_kzt=budget, duration_hours=duration, language=language, preferences=preferences,
                   min_budget_kzt=minimum, include_synthetic=include_synthetic, sort_by=sort_by)
