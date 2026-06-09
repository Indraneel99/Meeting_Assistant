from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.retrieval import QueryRequest
from meeting_assistant.services.embeddings import InMemoryEmbeddingIndex


@dataclass
class FixedEmbedder:
    vector: list[float]

    def embed(self, text: str) -> list[float]:
        return self.vector
from meeting_assistant.services.query import QueryService
from meeting_assistant.services.query_answerer import HeuristicQueryAnswerer, RetrievalContext
from meeting_assistant.services.retrieval_pagination import decode_cursor, encode_cursor, paginate_scored_results


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_paginate_scored_results_returns_cursor() -> None:
    items = [
        {"meeting_id": 3, "score": 0.9},
        {"meeting_id": 2, "score": 0.8},
        {"meeting_id": 1, "score": 0.7},
    ]
    page, next_cursor, has_more = paginate_scored_results(items, limit=2, cursor=None, id_key="meeting_id")

    assert len(page) == 2
    assert has_more is True
    assert next_cursor == encode_cursor(0.8, 2)

    page_two, next_cursor_two, has_more_two = paginate_scored_results(
        items,
        limit=2,
        cursor=next_cursor,
        id_key="meeting_id",
    )
    assert len(page_two) == 1
    assert has_more_two is False
    assert next_cursor_two is None
    assert decode_cursor(next_cursor) == (0.8, 2)


def test_semantic_decision_search_returns_scored_results() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("query-user", "query-user@example.com")
    meeting = repository.create_meeting(user.id, "Launch sync", None, "Transcript")
    repository.complete_meeting(
        meeting_id=meeting.id,
        summary_text="Discussed launch timing.",
        summary_embedding=[1.0, 0.0],
        tasks=[],
        decisions=[
            {
                "topic": "Launch",
                "decision_text": "Ship the batch pipeline first.",
                "topic_embedding": [1.0, 0.0],
            }
        ],
    )

    index = InMemoryEmbeddingIndex(embedder=FixedEmbedder([1.0, 0.0]))
    service = QueryService(repository, index, answerer=HeuristicQueryAnswerer(), settings=Settings())

    response = service.get_decisions(user.external_id, "pipeline rollout", limit=5)
    assert len(response.results) == 1
    assert response.results[0].decision_text == "Ship the batch pipeline first."
    assert response.results[0].score > 0


def test_chunk_search_uses_persisted_chunk_embeddings() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("chunk-user", "chunk-user@example.com")
    meeting = repository.create_meeting(user.id, "Design review", None, "Transcript")
    repository.replace_chunks(
        meeting.id,
        [
            ("Discussed API pagination and cursor design.", [1.0, 0.0]),
            ("Unrelated small talk about lunch.", [0.0, 1.0]),
        ],
    )

    index = InMemoryEmbeddingIndex(embedder=FixedEmbedder([1.0, 0.0]))
    service = QueryService(repository, index, answerer=HeuristicQueryAnswerer(), settings=Settings())

    response = service.search_chunks(user.external_id, "pagination cursor", limit=5)
    assert len(response.results) == 1
    assert "pagination" in response.results[0].text.lower()


def test_query_answer_includes_citations_and_synthesized_text() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("answer-user", "answer-user@example.com")
    meeting = repository.create_meeting(user.id, "Weekly product sync", None, "Transcript")
    repository.replace_chunks(
        meeting.id,
        [("Decision: ship the batch pipeline first.", [1.0, 0.0])],
    )
    repository.complete_meeting(
        meeting_id=meeting.id,
        summary_text="Team aligned on shipping the batch pipeline first.",
        summary_embedding=[1.0, 0.0],
        tasks=[],
        decisions=[
            {
                "topic": "Launch",
                "decision_text": "Ship the batch pipeline first.",
                "topic_embedding": [1.0, 0.0],
            }
        ],
    )

    index = InMemoryEmbeddingIndex(embedder=FixedEmbedder([1.0, 0.0]))
    service = QueryService(repository, index, answerer=HeuristicQueryAnswerer(), settings=Settings())

    response = service.answer(
        QueryRequest(user_external_id=user.external_id, question="What did we decide about the batch pipeline?")
    )

    assert "batch pipeline" in response.answer.lower()
    assert response.citations
    assert response.chunks
    assert response.decisions
    assert response.meetings
