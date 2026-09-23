"""Воспроизводимый генератор явно синтетических профилей по локальным JSON-правилам."""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from profile_database import ROOT, normalize_profile, parse_list

DEFAULT_RULES = ROOT / "synthetic_profile_rules.json"


# -----------------------------------------------------------------------------
# Правила: читает JSON-конфигурацию; пустой файл не подменяет выдуманными инструкциями.
# -----------------------------------------------------------------------------
def read_rules(path: Path = DEFAULT_RULES) -> dict[str, Any]:
    content = Path(path).read_text(encoding="utf-8-sig")
    if not content.strip():
        raise ValueError(f"Файл правил {path} пуст. Используйте synthetic_profile_rules.json")
    rules = json.loads(content)
    if not isinstance(rules, dict) or rules.get("version") != 1:
        raise ValueError("Нужен JSON-объект правил версии 1")
    if type(rules.get("seed")) is not int or rules["seed"] < 0:
        raise ValueError("seed должен быть целым неотрицательным числом")
    for name in ("cities", "language_sets", "max_hours", "templates"):
        if not isinstance(rules.get(name), list) or not rules[name]:
            raise ValueError(f"В правилах нужен непустой список {name}")
    if not parse_list(rules["cities"]) or any(not parse_list(items) for items in rules["language_sets"]):
        raise ValueError("Города и языки должны быть заполнены")
    for hours in rules["max_hours"]:
        if type(hours) not in (int, float) or not math.isfinite(hours) or hours <= 0:
            raise ValueError("Все значения max_hours должны быть положительными числами")
    probability = rules.get("busy_probability")
    if type(probability) not in (int, float) or not 0 <= probability <= 1:
        raise ValueError("busy_probability должна быть в диапазоне 0..1")
    start = date.fromisoformat(rules["calendar_start"])
    end = date.fromisoformat(rules["calendar_end"])
    if start > end:
        raise ValueError("Начало календаря позже окончания")
    for template in rules["templates"]:
        if not isinstance(template, dict) or not isinstance(template.get("category"), str) or not template["category"].strip():
            raise ValueError("У каждого шаблона должна быть категория")
        low, high = template.get("price_min"), template.get("price_max")
        if type(low) is not int or type(high) is not int or not 0 < low <= high:
            raise ValueError("Неверный диапазон цен в шаблоне")
        if low % 50000 or high % 50000:
            raise ValueError("Границы цены должны быть кратны 50000 тенге")
        descriptions = template.get("descriptions")
        if (not parse_list(template.get("event_formats")) or not isinstance(descriptions, list)
                or not descriptions or any(not isinstance(text, str) or not text.strip() for text in descriptions)):
            raise ValueError("Шаблону нужны форматы и описания")
        for description in descriptions:
            description.format(experience_years=1)
    return rules


# -----------------------------------------------------------------------------
# Генерация: использует фиксированный seed, отдельные ID и явные synthetic=True.
# -----------------------------------------------------------------------------
def generate_profiles(count: int = 30, rules_path: Path = DEFAULT_RULES) -> list[dict[str, Any]]:
    if type(count) is not int or count < 0:
        raise ValueError("Количество профилей должно быть целым неотрицательным числом")
    rules = read_rules(rules_path)
    rng = random.Random(rules["seed"])
    start = date.fromisoformat(rules["calendar_start"])
    end = date.fromisoformat(rules["calendar_end"])
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    result = []
    for index in range(count):
        template = rules["templates"][index % len(rules["templates"])]
        experience = rng.randint(1, 15)
        raw = {
            "id": f"SYN-v1-{rules['seed']}-{index + 1:04d}",
            "anon_name": f"Синтетический профиль {index + 1:03d}: {template['category']}",
            "categories": [template["category"]],
            "city": rng.choice(rules["cities"]), "city_imputed": False,
            "synthetic": True, "price_imputed": False,
            "price_from_kzt": rng.randrange(template["price_min"], template["price_max"] + 1, 50000),
            "event_formats": template["event_formats"],
            "languages": rng.choice(rules["language_sets"]),
            "max_hours": rng.choice(rules["max_hours"]),
            "busy_dates": [day.isoformat() for day in days if rng.random() < rules["busy_probability"]],
            "description": rng.choice(template["descriptions"]).format(experience_years=experience),
            "experience_years": experience,
        }
        result.append(normalize_profile(
            raw, source_type="generated", source_name=f"{Path(rules_path).name};seed={rules['seed']}",
            calendar_start=rules["calendar_start"], calendar_end=rules["calendar_end"],
        ))
    return result
