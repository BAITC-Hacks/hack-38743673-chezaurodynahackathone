"""Ручная проверка подключения к OpenAI для этапа ранжирования.

Перед запуском задайте AI_PROXY_API_KEY через set_test_key.ps1.
Сценарий отправляет один запрос к API и может расходовать средства проекта.
"""

from __future__ import annotations

import json

from smartmatch import rank_profiles


# -----------------------------------------------------------------------------
# Тестовые данные: имитируют строки, которые уже вернул модуль жёсткой фильтрации.
# -----------------------------------------------------------------------------
TEST_ORDER = {
    "preferences": "спокойный интеллигентный ведущий для деловой аудитории",
    "budget_kzt": 1_000_000,
    "language": "русский",
    "duration_hours": 6,
}
TEST_PROFILES = [
    {
        "id": "test-1", "description": "Веду деловые конференции спокойно и структурированно.",
        "price_from_kzt": 750_000, "languages": "русский|английский", "max_hours": 8,
        "synthetic": False, "city_imputed": False, "price_imputed": False,
    },
    {
        "id": "test-2", "description": "Провожу динамичные музыкальные конкурсы и вечеринки.",
        "price_from_kzt": 700_000, "languages": "русский", "max_hours": 6,
        "synthetic": False, "city_imputed": False, "price_imputed": False,
    },
]


# -----------------------------------------------------------------------------
# Запуск: проверяет ключ, endpoint и формат ответа модели на реальном запросе.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print(json.dumps(rank_profiles(TEST_ORDER, TEST_PROFILES), ensure_ascii=False, indent=2))
