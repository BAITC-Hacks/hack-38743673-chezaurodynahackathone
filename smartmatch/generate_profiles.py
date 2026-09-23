"""Deterministic, explicitly synthetic samples; never enabled by server startup."""
from __future__ import annotations

from datetime import timedelta
import json
import math
from pathlib import Path
import random

from .models import Contractor
from .repository import CALENDAR_START, CALENDAR_END

DEFAULT_RULES = Path(__file__).resolve().parents[1] / "data" / "synthetic_profile_rules.json"


def _strings(values) -> tuple[str, ...]:
    if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("Правила должны содержать непустые списки строк")
    return tuple(dict.fromkeys(value.strip() for value in values))


def read_rules(path: str | Path = DEFAULT_RULES) -> dict:
    rules = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(rules, dict) or rules.get("version") != 1:
        raise ValueError("Нужен JSON-объект правил версии 1")
    if type(rules.get("seed")) is not int or rules["seed"] < 0:
        raise ValueError("seed должен быть целым неотрицательным числом")
    _strings(rules.get("cities"))
    if not isinstance(rules.get("language_sets"), list) or not rules["language_sets"]:
        raise ValueError("Нужен список наборов языков")
    for values in rules["language_sets"]:
        _strings(values)
    hours = rules.get("max_hours")
    if not isinstance(hours, list) or not hours or any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in hours):
        raise ValueError("max_hours должен содержать положительные конечные числа")
    probability = rules.get("busy_probability")
    if type(probability) not in (int, float) or not 0 <= probability <= 1:
        raise ValueError("busy_probability должна быть в диапазоне 0..1")
    if (rules.get("calendar_start"), rules.get("calendar_end")) != (CALENDAR_START.isoformat(), CALENDAR_END.isoformat()):
        raise ValueError("Период генерации должен совпадать с календарём каталога")
    templates = rules.get("templates")
    if not isinstance(templates, list) or not templates:
        raise ValueError("Нужен непустой список шаблонов")
    for template in templates:
        if not isinstance(template, dict) or not isinstance(template.get("category"), str) or not template["category"].strip():
            raise ValueError("У шаблона должна быть категория")
        low, high = template.get("price_min"), template.get("price_max")
        if type(low) is not int or type(high) is not int or not 0 < low <= high or low % 50000 or high % 50000:
            raise ValueError("Неверный диапазон цен; границы должны быть кратны 50000")
        _strings(template.get("event_formats"))
        for text in _strings(template.get("descriptions")):
            if len(text.format(experience_years=1)) < 20:
                raise ValueError("Описание слишком короткое")
    return rules


def generate_profiles(count: int = 30, rules_path: str | Path = DEFAULT_RULES) -> list[dict]:
    if type(count) is not int or not 0 <= count <= 10000:
        raise ValueError("Количество профилей должно быть целым числом от 0 до 10000")
    rules = read_rules(rules_path)
    rng = random.Random(rules["seed"])
    days = [CALENDAR_START + timedelta(days=offset) for offset in range((CALENDAR_END - CALENDAR_START).days + 1)]
    result = []
    for index in range(count):
        template = rules["templates"][index % len(rules["templates"])]
        experience = rng.randint(1, 15)
        item = Contractor(
            id=f"SYN-v1-{rules['seed']}-{index + 1:04d}",
            name=f"Синтетический профиль {index + 1:03d}: {template['category']}",
            categories=(template["category"].strip(),), city=rng.choice(rules["cities"]).strip(),
            city_imputed=False, synthetic=True,
            price_from_kzt=rng.randrange(template["price_min"], template["price_max"] + 1, 50000),
            price_imputed=False, event_formats=tuple(dict.fromkeys(value.lower() for value in _strings(template["event_formats"]))),
            languages=tuple(dict.fromkeys(value.lower() for value in _strings(rng.choice(rules["language_sets"])))),
            max_hours=float(rng.choice(rules["max_hours"])),
            busy_dates=frozenset(day for day in days if rng.random() < rules["busy_probability"]),
            description=rng.choice(template["descriptions"]).format(experience_years=experience).strip(),
        )
        result.append({"contractor": item, "source_name": f"{Path(rules_path).name};seed={rules['seed']}",
                       "experience_years": experience})
    return result
