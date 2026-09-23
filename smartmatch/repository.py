from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path

from .models import Contractor


CALENDAR_START = date(2026, 9, 23)
CALENDAR_END = date(2026, 12, 31)


def _items(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in (value or "").split("|") if item.strip()))


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
        seen_ids: set[str] = set()
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                issues = cls._critical_issues(row)
                contractor_id = (row.get("id") or "").strip()
                if contractor_id and contractor_id in seen_ids:
                    issues.append("повторяющийся id")
                if issues:
                    quarantined.append({"row": row_number, "id": contractor_id, "issues": issues})
                    continue
                seen_ids.add(contractor_id)
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
                        event_formats=tuple(dict.fromkeys(x.lower() for x in _items(row["event_formats"]))),
                        languages=tuple(dict.fromkeys(x.lower() for x in _items(row["languages"]))),
                        max_hours=float(row["max_hours"]) if (row.get("max_hours") or "").strip() else None,
                        busy_dates=frozenset(date.fromisoformat(x) for x in _items(row["busy_dates"])),
                        description=row["description"].strip(),
                    )
                )
        return cls(tuple(contractors), tuple(quarantined))

    @staticmethod
    def _critical_issues(row: dict[str, str]) -> list[str]:
        checks = {
            "id": (row.get("id") or "").strip(),
            "имя": (row.get("anon_name") or "").strip(),
            "категория": _items(row.get("categories") or ""),
            "город": (row.get("city") or "").strip(),
            "формат": _items(row.get("event_formats") or ""),
            "язык": _items(row.get("languages") or ""),
            "описание": (row.get("description") or "").strip(),
        }
        issues = [f"нет поля: {label}" for label, value in checks.items() if not value]
        for flag in ("city_imputed", "synthetic", "price_imputed"):
            if str(row.get(flag, "")).strip().lower() not in {"true", "false", "1", "0", "yes", "no"}:
                issues.append(f"некорректный признак: {flag}")
        if None in row:
            issues.append("лишние столбцы CSV")
        try:
            if int(row.get("price_from_kzt") or "") <= 0:
                issues.append("цена должна быть больше нуля")
        except (TypeError, ValueError):
            issues.append("нет корректной цены")

        max_hours = (row.get("max_hours") or "").strip()
        if max_hours:
            try:
                if not math.isfinite(float(max_hours)) or float(max_hours) <= 0:
                    issues.append("длительность должна быть больше нуля")
            except ValueError:
                issues.append("некорректная длительность")

        busy_dates = (row.get("busy_dates") or "").strip()
        # An explicitly empty CSV field means no busy days in the declared calendar.
        # A missing field or a separators-only value is not an availability statement.
        if row.get("busy_dates") is None:
            issues.append("нет поля: календарь")
        elif busy_dates and not _items(busy_dates):
            issues.append("некорректный календарь занятости")
        if busy_dates:
            try:
                parsed_dates = [date.fromisoformat(value) for value in _items(busy_dates)]
                if any(value < CALENDAR_START or value > CALENDAR_END for value in parsed_dates):
                    issues.append("дата занятости вне календаря")
            except ValueError:
                issues.append("некорректная дата занятости")

        description = (row.get("description") or "").strip()
        if description and len(description) < 20:
            issues.append("описание слишком короткое")
        return issues

    def metadata(self) -> dict:
        return {
            "contractors": len(self.contractors),
            "quarantined_count": len(self.quarantined),
            "quarantined": list(self.quarantined),
            "cities": sorted({item.city for item in self.contractors}),
            "categories": sorted({value for item in self.contractors for value in item.categories}),
            "event_formats": sorted({value for item in self.contractors for value in item.event_formats}),
            "languages": sorted({value for item in self.contractors for value in item.languages}),
            "calendar": {"min": CALENDAR_START.isoformat(), "max": CALENDAR_END.isoformat()},
            "synthetic_count": sum(item.synthetic for item in self.contractors),
            "price_imputed_count": sum(item.price_imputed for item in self.contractors),
            "city_imputed_count": sum(item.city_imputed for item in self.contractors),
        }
