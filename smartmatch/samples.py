"""Shared reproducible demo requests; no external API required."""

DEMO_CASES = [
    {
        "name": "Плотная категория",
        "description": "Нужен интеллигентный ведущий на корпоратив в Алматы 6 октября 2026 года. Бюджет до 1 млн тенге, 5 часов, русский язык. Для бизнес-аудитории, без навязчивых конкурсов.",
        "query": {
            "city": "Алматы", "event_date": "2026-10-06", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 1000000, "duration_hours": 5,
            "language": "русский", "preferences": "интеллигентный ведущий для бизнес-аудитории",
        },
    },
    {
        "name": "Редкая категория",
        "description": "Ищем флориста на свадьбу в Алматы 4 октября 2026 года. Бюджет до 500 000 тенге. Русский язык. Нужно авторское цветочное оформление.",
        "query": {
            "city": "Алматы", "event_date": "2026-10-04", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 500000, "duration_hours": None,
            "language": "русский", "preferences": "авторское цветочное оформление",
        },
    },
    {
        "name": "Условия не проходят",
        "description": "Нужен ведущий на корпоратив в Алматы 31 декабря 2026 года. Бюджет до 100 000 тенге, 8 часов, казахский язык.",
        "query": {
            "city": "Алматы", "event_date": "2026-12-31", "event_format": "корпоратив",
            "category": "Ведущий", "budget_kzt": 100000, "duration_hours": 8,
            "language": "казахский", "preferences": "",
        },
    },
    {
        "name": "Категории нет",
        "description": "Нужен флорист на свадьбу за рубежом 15 октября 2026 года. Бюджет до 1 млн тенге, русский язык.",
        "query": {
            "city": "Зарубежье", "event_date": "2026-10-15", "event_format": "свадьба",
            "category": "Флорист", "budget_kzt": 1000000, "duration_hours": None,
            "language": "русский", "preferences": "",
        },
    },
]
