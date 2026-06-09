from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.db.models import Base
from meeting_assistant.repositories import Repository
from meeting_assistant.services.embeddings import (
    EmbeddingRouter,
    HeuristicEmbedder,
    InMemoryEmbeddingIndex,
    OpenAIEmbedder,
    cosine_similarity,
    pad_embedding,
)


@dataclass
class FixedEmbedder:
    vector: list[float]

    def embed(self, text: str) -> list[float]:
        return self.vector


@dataclass
class FakeEmbeddingData:
    embedding: list[float]


@dataclass
class FakeEmbeddingsResponse:
    data: list[FakeEmbeddingData]


@dataclass
class FakeEmbeddingsClient:
    response: FakeEmbeddingsResponse | None = None
    error: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    def create(self, *, input: list[str], model: str) -> FakeEmbeddingsResponse:
        self.calls.append({"input": input, "model": model})
        if self.error:
            raise self.error
        if self.response is None:
            raise ValueError("Missing fake embeddings response.")
        return self.response


@dataclass
class FakeOpenAIClient:
    embeddings: FakeEmbeddingsClient


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_inmemory_search_uses_persisted_embedding() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("embed-user", "embed-user@example.com")
    meeting = repository.create_meeting(user.id, "Launch sync", None, "Transcript")
    repository.complete_meeting(
        meeting_id=meeting.id,
        summary_text="Discussed launch timing and rollout risks.",
        summary_embedding=[1.0, 0.0],
        tasks=[],
        decisions=[],
    )

    index = InMemoryEmbeddingIndex(embedder=FixedEmbedder([1.0, 0.0]))
    results, next_cursor, has_more = index.search_for_user(
        repository,
        user.id,
        "completely unrelated query",
        limit=5,
    )

    assert len(results) == 1
    assert results[0]["meeting_id"] == meeting.id
    assert results[0]["score"] == 1.0
    assert next_cursor is None
    assert has_more is False


def test_heuristic_embedder_and_padding() -> None:
    embedder = HeuristicEmbedder()
    vector = embedder.embed("ship launch ship")
    padded = pad_embedding(vector, 5)

    assert vector
    assert len(padded) == 5
    assert cosine_similarity(vector, padded) > 0


def test_openai_embedder_returns_hosted_vector() -> None:
    embeddings = FakeEmbeddingsClient(
        response=FakeEmbeddingsResponse(data=[FakeEmbeddingData(embedding=[0.1, 0.2, 0.3])])
    )
    embedder = OpenAIEmbedder(
        api_key="test-key",
        model_name="text-embedding-3-small",
        base_url="https://api.openai.com/v1",
        timeout_seconds=5.0,
        client=FakeOpenAIClient(embeddings=embeddings),
    )

    vector = embedder.embed("What did we decide about launch?")

    assert vector == [0.1, 0.2, 0.3]
    assert embeddings.calls[0]["model"] == "text-embedding-3-small"


def test_embedding_router_falls_back_when_primary_fails() -> None:
    router = EmbeddingRouter(
        primary=OpenAIEmbedder(
            api_key="test-key",
            model_name="text-embedding-3-small",
            base_url="https://api.openai.com/v1",
            timeout_seconds=5.0,
            client=FakeOpenAIClient(embeddings=FakeEmbeddingsClient(error=RuntimeError("boom"))),
        ),
        fallback=FixedEmbedder([0.5, 0.5]),
    )

    vector = router.embed("fallback query")

    assert vector == [0.5, 0.5]
