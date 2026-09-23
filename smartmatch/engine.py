from __future__ import annotations

from collections import Counter
from datetime import date

from .models import Contractor, SearchQuery
from .repository import ContractorRepository
from .text import TextIndex


MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
LANGUAGE_CASE = {"русский": "русском", "казахский": "казахском", "английский": "английском"}


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₸"


def date_ru(value: date) -> str:
    return f"{value.day} {MONTHS[value.month]}"


class RecommendationEngine:
    def __init__(self, repository: ContractorRepository) -> None:
        self.repository = repository
        documents = {item.id: item.description for item in repository.contractors}
        self.text_index = TextIndex(documents)
        meta = repository.metadata()
        self.min_date = date.fromisoformat(meta["calendar"]["min"])
        self.max_date = date.fromisoformat(meta["calendar"]["max"])

    def recommend(self, query: SearchQuery, limit: int = 3) -> dict:
        if not self.min_date <= query.event_date <= self.max_date:
            raise ValueError(
                f"Дата вне календаря датасета: выберите день с {self.min_date.isoformat()} по {self.max_date.isoformat()}"
            )

        market = [
            item for item in self.repository.contractors
            if item.city.casefold() == query.city.casefold()
            and any(value.casefold() == query.category.casefold() for value in item.categories)
        ]
        if not market:
            return self._empty_market(query)

        stages = [
            {"stage": "Исходный каталог", "remaining": len(self.repository.contractors) + len(self.repository.quarantined)},
            {"stage": "Критические данные заполнены", "remaining": len(self.repository.contractors)},
            {"stage": "Город и категория", "remaining": len(market)},
        ]
        current = market
        checks = (
            ("Свободны в дату", lambda item: query.event_date not in item.busy_dates),
            ("В рамках бюджета", lambda item: item.price_from_kzt <= query.budget_kzt),
            ("Берут формат", lambda item: query.event_format in item.event_formats),
            ("Работают на языке", lambda item: not query.language or query.language in item.languages),
            (
                "Подходят по длительности",
                lambda item: query.duration_hours is None or item.max_hours is None or query.duration_hours <= item.max_hours,
            ),
        )
        for label, check in checks:
            current = [item for item in current if check(item)]
            stages.append({"stage": label, "remaining": len(current)})

        exclusions = self._exclusions(market, query)
        if not current:
            return {
                "status": "no_eligible",
                "title": "Кандидаты есть, но ни один не проходит условия",
                "message": self._failure_message(market, exclusions),
                "results": [],
                "pipeline": stages,
                "exclusions": exclusions,
                "market_count": len(market),
                "eligible_count": 0,
                "data_quality_excluded": len(self.repository.quarantined),
            }

        ranked = sorted(
            (self._rank(item, query) for item in current),
            key=lambda row: (-row["score"], row["price_from_kzt"], row["id"]),
        )
        results = ranked[:limit]
        if len(current) < limit:
            message = self._partial_message(len(current), len(market), exclusions)
        else:
            message = f"Из {len(market)} профилей условия прошли {len(current)}. Показаны три с самым сильным подтверждённым совпадением."

        return {
            "status": "success",
            "title": f"Подобрали {len(results)} из {len(current)} подходящих",
            "message": message,
            "results": results,
            "pipeline": stages,
            "exclusions": exclusions,
            "market_count": len(market),
            "eligible_count": len(current),
            "data_quality_excluded": len(self.repository.quarantined),
        }

    def _rank(self, item: Contractor, query: SearchQuery) -> dict:
        query_text = " ".join(
            value for value in (
                query.category, query.event_format, query.language or "", query.preferences,
            ) if value
        )
        semantic, matched = self.text_index.similarity(item.id, query_text)
        ratio = item.price_from_kzt / query.budget_kzt
        budget_fit = max(0.0, 1 - abs(ratio - 0.72) / 0.72)
        language_fit = 1.0 if query.language and query.language in item.languages else 0.65
        duration_fit = 0.65
        if query.duration_hours is not None:
            if item.max_hours is None:
                duration_fit = 0.8
            else:
                duration_fit = min(1.0, 0.75 + (item.max_hours - query.duration_hours) / max(item.max_hours, 1) * 0.25)
        provenance = (
            1.0
            - (0.04 if item.synthetic else 0.0)
            - (0.04 if item.price_imputed else 0.0)
            - (0.04 if item.city_imputed else 0.0)
        )
        total = (
            0.34 * semantic
            + 0.30 * budget_fit
            + 0.12 * language_fit
            + 0.10 * duration_fit
            + 0.14 * provenance
        )
        evidence = self.text_index.evidence_sentence(item.id, matched)
        explanation = self._explanation(item, query, evidence)
        return {
            "id": item.id,
            "name": item.name,
            "category": query.category,
            "city": item.city,
            "price_from_kzt": item.price_from_kzt,
            "price_imputed": item.price_imputed,
            "city_imputed": item.city_imputed,
            "synthetic": item.synthetic,
            "event_formats": list(item.event_formats),
            "languages": list(item.languages),
            "max_hours": item.max_hours,
            "score": round(total * 100, 2),
            "score_factors": {
                "смысл описания": round(semantic * 100),
                "соответствие бюджету": round(budget_fit * 100),
                "язык": round(language_fit * 100),
                "длительность": round(duration_fit * 100),
                "качество исходных данных": round(provenance * 100),
            },
            "matched_terms": matched,
            "explanation": explanation,
        }

    def _explanation(self, item: Contractor, query: SearchQuery, evidence: str) -> str:
        reserve = query.budget_kzt - item.price_from_kzt
        first = (
            f"Свободен {date_ru(query.event_date)}; цена от {money(item.price_from_kzt)} "
            f"укладывается в бюджет с запасом {money(reserve)}."
        )
        details: list[str] = []
        if query.language:
            details.append(f"работает на {LANGUAGE_CASE.get(query.language, query.language)} языке")
        if query.duration_hours is not None and item.max_hours is not None:
            details.append(f"берёт до {item.max_hours:g} ч при запросе на {query.duration_hours:g} ч")
        if evidence:
            second = f"В описании есть конкретный факт: «{evidence}»"
            if details:
                second += "; " + " и ".join(details)
            second += "."
        else:
            second = f"Берёт формат «{query.event_format}»"
            if details:
                second += "; " + ", ".join(details)
            second += "."
        return first + " " + second

    @staticmethod
    def _exclusions(market: list[Contractor], query: SearchQuery) -> dict[str, int]:
        return {
            "заняты в выбранную дату": sum(query.event_date in item.busy_dates for item in market),
            "дороже бюджета": sum(item.price_from_kzt > query.budget_kzt for item in market),
            "не берут формат": sum(query.event_format not in item.event_formats for item in market),
            "нет нужного языка": sum(bool(query.language) and query.language not in item.languages for item in market),
            "не подходят по длительности": sum(
                query.duration_hours is not None and item.max_hours is not None and query.duration_hours > item.max_hours
                for item in market
            ),
        }

    @staticmethod
    def _failure_message(market: list[Contractor], exclusions: dict[str, int]) -> str:
        parts = [f"{count} {label}" for label, count in exclusions.items() if count]
        reasons = ", ".join(parts) if parts else "условия не выполнены"
        return f"В городе и категории найдено {len(market)} профилей, но после проверки не осталось ни одного: {reasons}. Причины могут пересекаться."

    @staticmethod
    def _partial_message(eligible: int, market: int, exclusions: dict[str, int]) -> str:
        parts = [f"{count} {label}" for label, count in exclusions.items() if count]
        reasons = ", ".join(parts) if parts else "других профилей в каталоге нет"
        return f"Показаны все {eligible} подходящих профиля из {market}. До трёх не добрали: {reasons}. Причины могут пересекаться."

    def _empty_market(self, query: SearchQuery) -> dict:
        return {
            "status": "no_market",
            "title": "В этом городе такой категории нет",
            "message": f"В каталоге нет профилей категории «{query.category}» для города {query.city}. Условия даты и бюджета не применялись.",
            "results": [],
            "pipeline": [
                {"stage": "Исходный каталог", "remaining": len(self.repository.contractors) + len(self.repository.quarantined)},
                {"stage": "Критические данные заполнены", "remaining": len(self.repository.contractors)},
                {"stage": "Город и категория", "remaining": 0},
            ],
            "exclusions": {},
            "market_count": 0,
            "eligible_count": 0,
            "data_quality_excluded": len(self.repository.quarantined),
        }

