"""Application workflow shared by the HTTP interface and integration checks."""
from dataclasses import asdict
from pathlib import Path

from .ai import AIService, recommend_with_ai
from .brief import parse_brief
from .database import Database
from .engine import RecommendationEngine
from .models import SearchQuery


class MatchingService:
    def __init__(self, database: Database, csv_path: Path, ai: AIService):
        self.database = database
        self.engine = RecommendationEngine(database.initialize(csv_path))
        self.ai = ai

    def parse(self, description: str, use_ai: bool) -> dict:
        return parse_brief(description, self.engine.repository.metadata(), self.ai, use_ai)

    def recommend(self, payload: dict) -> dict:
        query = SearchQuery.from_dict(payload)
        use_ai = payload.get("use_ai", True)
        result = recommend_with_ai(self.engine, query, self.ai, use_ai)
        request = {**asdict(query), "event_date": query.event_date.isoformat(), "use_ai": use_ai}
        search_id = self.database.record_search(request, result)
        return {**result, "search_id": search_id, "saved": True}
