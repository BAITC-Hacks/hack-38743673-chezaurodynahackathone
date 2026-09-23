from __future__ import annotations

from dataclasses import dataclass

from .models import Contractor, SearchQuery


@dataclass(frozen=True, slots=True)
class Rejection:
    contractor_id: str
    reasons: tuple[str, ...]


class HardFilter:
    """Deterministic eligibility gate. Ranking never sees rejected profiles."""

    @staticmethod
    def checks(item: Contractor, query: SearchQuery) -> tuple[tuple[str, str, bool], ...]:
        return (
            (
                "Нужный тип профиля",
                "синтетические профили отключены",
                query.include_synthetic or not item.synthetic,
            ),
            (
                "Свободны в дату",
                "занят в выбранную дату",
                query.event_date not in item.busy_dates,
            ),
            (
                "В рамках бюджета",
                "дороже бюджета",
                item.price_from_kzt <= query.budget_kzt,
            ),
            (
                "Не ниже минимальной цены",
                "цена ниже нижней границы",
                item.price_from_kzt >= query.min_budget_kzt,
            ),
            (
                "Берут формат",
                "не берёт формат",
                query.event_format in item.event_formats,
            ),
            (
                "Работают на языке",
                "нет нужного языка",
                not query.language or query.language in item.languages,
            ),
            (
                "Подходят по длительности",
                "не подходит по длительности",
                query.duration_hours is None
                or item.max_hours is None
                or query.duration_hours <= item.max_hours,
            ),
        )

    @classmethod
    def apply(cls, candidates: list[Contractor], query: SearchQuery) -> dict:
        stage_counts: list[dict[str, int | str]] = []
        current = candidates
        for index, (stage, _, _) in enumerate(cls.checks(candidates[0], query) if candidates else ()):
            current = [item for item in current if cls.checks(item, query)[index][2]]
            stage_counts.append({"stage": stage, "remaining": len(current)})

        rejections: list[Rejection] = []
        for item in candidates:
            reasons = tuple(reason for _, reason, passed in cls.checks(item, query) if not passed)
            if reasons:
                rejections.append(Rejection(item.id, reasons))

        accepted_ids = {item.id for item in current}
        accepted = [item for item in candidates if item.id in accepted_ids]
        exclusions: dict[str, int] = {}
        for rejection in rejections:
            for reason in rejection.reasons:
                exclusions[reason] = exclusions.get(reason, 0) + 1

        return {
            "accepted": accepted,
            "stages": stage_counts,
            "exclusions": exclusions,
            "rejections": rejections,
        }
