from __future__ import annotations

import math
from collections import Counter

from meeting_assistant.repositories import Repository


def _tokenize(text: str) -> list[str]:
    return [token.strip(".,!?():;\"'").lower() for token in text.split() if token.strip()]


def _vectorize(text: str) -> list[float]:
    counts = Counter(_tokenize(text))
    if not counts:
        return []
    keys = sorted(counts)
    return [float(counts[key]) for key in keys]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = max(len(left), len(right))
    left_padded = left + [0.0] * (size - len(left))
    right_padded = right + [0.0] * (size - len(right))
    numerator = sum(a * b for a, b in zip(left_padded, right_padded, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left_padded))
    right_norm = math.sqrt(sum(b * b for b in right_padded))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


class InMemoryEmbeddingIndex:
    def embed(self, text: str) -> list[float]:
        return _vectorize(text)

    def search_for_user(self, repository: Repository, user_id: int, query: str, limit: int) -> list[dict[str, object]]:
        query_embedding = self.embed(query)
        meetings = repository.get_meetings_for_user(user_id)
        scored = []
        for meeting in meetings:
            embedding = self.embed(meeting.summary_text)
            score = _cosine_similarity(query_embedding, embedding)
            if score > 0:
                scored.append(
                    {
                        "meeting_id": meeting.id,
                        "title": meeting.title,
                        "summary": meeting.summary_text,
                        "score": round(score, 4),
                    }
                )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]
