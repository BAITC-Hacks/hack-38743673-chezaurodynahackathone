from __future__ import annotations

import math
import re
from collections import Counter


TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
STOPWORDS = {
    "а", "без", "бы", "был", "была", "были", "было", "в", "ваш", "во", "все",
    "для", "до", "его", "ее", "за", "и", "из", "или", "их", "к", "как", "мы",
    "на", "не", "но", "о", "об", "от", "по", "под", "при", "с", "со", "так", "у",
    "уже", "что", "это", "этот", "я", "the", "and", "for", "with",
}
SUFFIXES = (
    "иями", "ями", "ами", "его", "ого", "ему", "ому", "ыми", "ими", "ией", "ий",
    "ый", "ая", "яя", "ое", "ее", "ов", "ев", "ам", "ям", "ах", "ях", "ом", "ем",
    "ы", "и", "а", "я", "у", "ю", "е", "о",
)


def stem(token: str) -> str:
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokens(text: str) -> list[str]:
    return [stem(token.lower()) for token in TOKEN_RE.findall(text) if token.lower() not in STOPWORDS]


class TextIndex:
    def __init__(self, documents: dict[str, str]) -> None:
        self.documents = documents
        tokenized = {key: tokens(value) for key, value in documents.items()}
        count = max(len(tokenized), 1)
        document_frequency = Counter(token for values in tokenized.values() for token in set(values))
        self.idf = {token: math.log((count + 1) / (freq + 1)) + 1 for token, freq in document_frequency.items()}
        self.vectors = {key: self._vector(values) for key, values in tokenized.items()}

    def _vector(self, values: list[str]) -> dict[str, float]:
        counts = Counter(values)
        weighted = {token: (1 + math.log(freq)) * self.idf.get(token, 1.0) for token, freq in counts.items()}
        norm = math.sqrt(sum(weight * weight for weight in weighted.values())) or 1.0
        return {token: weight / norm for token, weight in weighted.items()}

    def similarity(self, document_id: str, query: str) -> tuple[float, list[str]]:
        query_vector = self._vector(tokens(query))
        document_vector = self.vectors[document_id]
        shared = set(query_vector) & set(document_vector)
        score = sum(query_vector[token] * document_vector[token] for token in shared)
        ranked = sorted(shared, key=lambda token: (-self.idf.get(token, 1.0), token))
        return score, ranked[:4]

    def evidence_sentence(self, document_id: str, matched: list[str]) -> str:
        description = self.documents[document_id]
        sentences = [value.strip() for value in SENTENCE_RE.split(description) if value.strip()]
        if not sentences:
            return ""
        matched_set = set(matched)
        best = max(
            sentences,
            key=lambda value: (sum(self.idf.get(token, 1.0) for token in set(tokens(value)) & matched_set), -len(value)),
        )
        if len(best) > 170:
            best = best[:167].rsplit(" ", 1)[0] + "…"
        return best.rstrip(".!? ")

