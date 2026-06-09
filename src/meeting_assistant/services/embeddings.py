from __future__ import annotations

import json
import logging
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from openai import OpenAI

from meeting_assistant.core.config import Settings
from meeting_assistant.repositories import Repository
from meeting_assistant.services.retrieval_pagination import paginate_scored_results

logger = logging.getLogger("uvicorn.error")


def _tokenize(text: str) -> list[str]:
    return [token.strip(".,!?():;\"'").lower() for token in text.split() if token.strip()]


def pad_embedding(vector: list[float], dimensions: int) -> list[float]:
    if len(vector) >= dimensions:
        return vector[:dimensions]
    return vector + [0.0] * (dimensions - len(vector))


def cosine_similarity(left: list[float], right: list[float]) -> float:
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


def parse_embedding(value: list[float] | str | None) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, str):
        if not value or value == "[]":
            return []
        return [float(item) for item in json.loads(value)]
    return [float(item) for item in value]


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class EmbeddingIndex(Protocol):
    def embed(self, text: str) -> list[float]:
        ...

    def search_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        ...

    def search_chunks_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        ...

    def search_decisions_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        ...


class HeuristicEmbedder:
    """Development embedder using bag-of-words vectors."""

    def embed(self, text: str) -> list[float]:
        counts = Counter(_tokenize(text))
        if not counts:
            return []
        keys = sorted(counts)
        return [float(counts[key]) for key in keys]


class OpenAIEmbeddingsClient(Protocol):
    def create(self, *, input: list[str], model: str) -> Any:
        ...


class OpenAIClient(Protocol):
    embeddings: OpenAIEmbeddingsClient


class OpenAIEmbedder:
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str,
        timeout_seconds: float,
        client: OpenAI | OpenAIClient | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.model_name = model_name
        if client is not None:
            self._client = client
        else:
            self._client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_seconds,
                http_client=http_client,
            )

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            return []
        logger.info("Embedder provider=openai model=%s", self.model_name)
        response = self._client.embeddings.create(input=[text], model=self.model_name)
        return [float(value) for value in response.data[0].embedding]


@dataclass(slots=True)
class EmbeddingRouter:
    primary: Embedder
    fallback: Embedder | None = None

    def embed(self, text: str) -> list[float]:
        try:
            return self.primary.embed(text)
        except Exception:
            logger.exception("Primary embedder failed; attempting fallback.")
            if self.fallback is None:
                raise
            return self.fallback.embed(text)


@dataclass(slots=True)
class InMemoryEmbeddingIndex:
    embedder: Embedder
    dimensions: int | None = None

    def embed(self, text: str) -> list[float]:
        vector = self.embedder.embed(text)
        if self.dimensions is not None:
            return pad_embedding(vector, self.dimensions)
        return vector

    def search_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        query_embedding = self.embed(query)
        meetings = repository.get_meetings_for_user(user_id)
        scored = []
        for meeting in meetings:
            stored_embedding = parse_embedding(meeting.summary_embedding)
            if not stored_embedding:
                continue
            score = cosine_similarity(query_embedding, stored_embedding)
            if score > 0:
                scored.append(
                    {
                        "meeting_id": meeting.id,
                        "title": meeting.title,
                        "summary": meeting.summary_text,
                        "score": round(score, 4),
                    }
                )
        scored.sort(key=lambda item: (item["score"], item["meeting_id"]), reverse=True)
        return paginate_scored_results(scored, limit=limit, cursor=cursor, id_key="meeting_id")

    def search_chunks_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        query_embedding = self.embed(query)
        scored = []
        for chunk, title in repository.get_chunks_for_user(user_id):
            stored_embedding = parse_embedding(chunk.chunk_embedding)
            if not stored_embedding:
                continue
            score = cosine_similarity(query_embedding, stored_embedding)
            if score > 0:
                scored.append(
                    {
                        "chunk_id": chunk.id,
                        "meeting_id": chunk.meeting_id,
                        "meeting_title": title,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "score": round(score, 4),
                    }
                )
        scored.sort(key=lambda item: (item["score"], item["chunk_id"]), reverse=True)
        return paginate_scored_results(scored, limit=limit, cursor=cursor, id_key="chunk_id")

    def search_decisions_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        query_embedding = self.embed(query)
        scored = []
        for decision in repository.get_decisions_for_user(user_id):
            stored_embedding = parse_embedding(decision.topic_embedding)
            if not stored_embedding:
                continue
            score = cosine_similarity(query_embedding, stored_embedding)
            if score > 0:
                scored.append(
                    {
                        "decision_id": decision.id,
                        "meeting_id": decision.meeting_id,
                        "topic": decision.topic,
                        "decision_text": decision.decision_text,
                        "score": round(score, 4),
                    }
                )
        scored.sort(key=lambda item: (item["score"], item["decision_id"]), reverse=True)
        return paginate_scored_results(scored, limit=limit, cursor=cursor, id_key="decision_id")


@dataclass(slots=True)
class PgVectorEmbeddingIndex:
    embedder: Embedder
    dimensions: int

    def embed(self, text: str) -> list[float]:
        return pad_embedding(self.embedder.embed(text), self.dimensions)

    def search_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        query_embedding = self.embed(query)
        return repository.search_meetings_by_embedding(
            user_id,
            query_embedding,
            limit,
            cursor=cursor,
        )

    def search_chunks_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        query_embedding = self.embed(query)
        return repository.search_chunks_by_embedding(
            user_id,
            query_embedding,
            limit,
            cursor=cursor,
        )

    def search_decisions_for_user(
        self,
        repository: Repository,
        user_id: int,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        query_embedding = self.embed(query)
        return repository.search_decisions_by_embedding(
            user_id,
            query_embedding,
            limit,
            cursor=cursor,
        )


def build_embedding_index(settings: Settings) -> EmbeddingIndex:
    heuristic = HeuristicEmbedder()
    if settings.embedding_provider == "openai" and settings.embedding_openai_api_key:
        embedder: Embedder = EmbeddingRouter(
            primary=OpenAIEmbedder(
                api_key=settings.embedding_openai_api_key,
                model_name=settings.embedding_openai_model,
                base_url=settings.embedding_openai_base_url,
                timeout_seconds=settings.embedding_openai_timeout_seconds,
            ),
            fallback=heuristic if settings.embedding_fallback_provider == "heuristic" else None,
        )
    else:
        embedder = heuristic

    if settings.database_url.startswith("postgresql"):
        return PgVectorEmbeddingIndex(embedder=embedder, dimensions=settings.embedding_dimensions)
    return InMemoryEmbeddingIndex(embedder=embedder)
