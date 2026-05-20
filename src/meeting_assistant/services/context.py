from dataclasses import dataclass

from meeting_assistant.repositories import Repository
from meeting_assistant.services.embeddings import InMemoryEmbeddingIndex


@dataclass(slots=True)
class ContextBundle:
    recent_summaries: list[str]
    relevant_summaries: list[str]


class ContextLoader:
    def __init__(self, repository: Repository, embedding_index: InMemoryEmbeddingIndex) -> None:
        self.repository = repository
        self.embedding_index = embedding_index

    def load(self, user_id: int, transcript_text: str, recent_limit: int = 3, relevant_limit: int = 5) -> ContextBundle:
        recent = self.repository.list_recent_meetings(user_id, recent_limit)
        relevant = self.embedding_index.search_for_user(self.repository, user_id, transcript_text, relevant_limit)
        return ContextBundle(
            recent_summaries=[meeting.summary_text for meeting in recent],
            relevant_summaries=[item["summary"] for item in relevant],
        )
