from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import Contractor


def _items(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split("|") if item.strip())


def _flag(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


class ContractorRepository:
    def __init__(self, contractors: tuple[Contractor, ...], quarantined: tuple[dict, ...] = ()) -> None:
        if not contractors:
            raise ValueError("Каталог подрядчиков пуст")
        ids = [item.id for item in contractors]
        if len(ids) != len(set(ids)):
            raise ValueError("В каталоге есть повторяющиеся id")
        self.contractors = contractors
        self.quarantined = quarantined

    @classmethod
    def from_csv(cls, path: str | Path) -> "ContractorRepository":
        contractors: list[Contractor] = []
        quarantined: list[dict] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                issues = cls._critical_issues(row)
                if issues:
                    quarantined.append({"row": row_number, "id": row.get("id", ""), "issues": issues})
                    continue
                contractors.append(
                    Contractor(
                        id=row["id"].strip(),
                        name=row["anon_name"].strip(),
                        categories=_items(row["categories"]),
                        city=row["city"].strip(),
                        city_imputed=_flag(row["city_imputed"]),
                        synthetic=_flag(row["synthetic"]),
                        price_from_kzt=int(row["price_from_kzt"]),
                        price_imputed=_flag(row["price_imputed"]),
                        event_formats=tuple(x.lower() for x in _items(row["event_formats"])),
                        languages=tuple(x.lower() for x in _items(row["languages"])),
                        max_hours=float(row["max_hours"]) if row["max_hours"].strip() else None,
                        busy_dates=frozenset(date.fromisoformat(x) for x in _items(row["busy_dates"])),
                        description=row["description"].strip(),
                    )
                )
        return cls(tuple(contractors), tuple(quarantined))

    @staticmethod
    def _critical_issues(row: dict[str, str]) -> list[str]:
        checks = {
            "id": row.get("id", "").strip(),
            "имя": row.get("anon_name", "").strip(),
            "категория": row.get("categories", "").strip(),
            "город": row.get("city", "").strip(),
            "формат": row.get("event_formats", "").strip(),
            "язык": row.get("languages", "").strip(),
            "календарь": row.get("busy_dates", "").strip(),
            "описание": row.get("description", "").strip(),
        }
        issues = [f"нет поля: {label}" for label, value in checks.items() if not value]
        try:
            if int(row.get("price_from_kzt", "")) <= 0:
                issues.append("цена должна быть больше нуля")
        except (TypeError, ValueError):
            issues.append("нет корректной цены")
        return issues

    def metadata(self) -> dict:
        dates = [day for item in self.contractors for day in item.busy_dates]
        return {
            "contractors": len(self.contractors),
            "quarantined_count": len(self.quarantined),
            "quarantined": list(self.quarantined),
            "cities": sorted({item.city for item in self.contractors}),
            "categories": sorted({value for item in self.contractors for value in item.categories}),
            "event_formats": sorted({value for item in self.contractors for value in item.event_formats}),
            "languages": sorted({value for item in self.contractors for value in item.languages}),
            "calendar": {"min": min(dates).isoformat(), "max": max(dates).isoformat()},
            "synthetic_count": sum(item.synthetic for item in self.contractors),
            "price_imputed_count": sum(item.price_imputed for item in self.contractors),
            "city_imputed_count": sum(item.city_imputed for item in self.contractors),
        }

