from meeting_assistant.core.config import Settings
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.retrieval import (
    ChunkSearchResult,
    DecisionItem,
    MeetingSearchResult,
    MeetingTask,
    MeetingTasksResponse,
    PaginatedChunkSearchResponse,
    PaginatedDecisionsResponse,
    PaginatedSearchMeetingsResponse,
    QueryRequest,
    QueryResponse,
)
from meeting_assistant.services.embeddings import EmbeddingIndex
from meeting_assistant.services.query_answerer import QueryAnswerer, RetrievalContext, build_query_answerer


class QueryService:
    def __init__(
        self,
        repository: Repository,
        embedding_index: EmbeddingIndex,
        *,
        answerer: QueryAnswerer | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository
        self.embedding_index = embedding_index
        self.settings = settings or Settings()
        self.answerer = answerer or build_query_answerer(self.settings)

    def search_past_meetings(
        self,
        user_external_id: str,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> PaginatedSearchMeetingsResponse:
        user = self.repository.get_user_by_external_id(user_external_id)
        if not user:
            return PaginatedSearchMeetingsResponse(results=[])

        results, next_cursor, has_more = self.embedding_index.search_for_user(
            self.repository,
            user.id,
            query,
            limit,
            cursor=cursor,
        )
        return PaginatedSearchMeetingsResponse(
            results=[MeetingSearchResult(**item) for item in results],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def search_chunks(
        self,
        user_external_id: str,
        query: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> PaginatedChunkSearchResponse:
        user = self.repository.get_user_by_external_id(user_external_id)
        if not user:
            return PaginatedChunkSearchResponse(results=[])

        results, next_cursor, has_more = self.embedding_index.search_chunks_for_user(
            self.repository,
            user.id,
            query,
            limit,
            cursor=cursor,
        )
        return PaginatedChunkSearchResponse(
            results=[ChunkSearchResult(**item) for item in results],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def get_meeting_tasks(self, meeting_id: int) -> MeetingTasksResponse:
        tasks = self.repository.get_tasks_for_meeting(meeting_id)
        return MeetingTasksResponse(
            meeting_id=meeting_id,
            tasks=[MeetingTask(assignee=task.assignee, action=task.action, status=task.status) for task in tasks],
        )

    def get_decisions(
        self,
        user_external_id: str,
        topic: str,
        limit: int,
        *,
        cursor: str | None = None,
    ) -> PaginatedDecisionsResponse:
        user = self.repository.get_user_by_external_id(user_external_id)
        if not user:
            return PaginatedDecisionsResponse(results=[])

        results, next_cursor, has_more = self.embedding_index.search_decisions_for_user(
            self.repository,
            user.id,
            topic,
            limit,
            cursor=cursor,
        )
        return PaginatedDecisionsResponse(
            results=[DecisionItem(**item) for item in results],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def answer(self, payload: QueryRequest) -> QueryResponse:
        meetings = self.search_past_meetings(
            payload.user_external_id,
            payload.question,
            self.settings.query_top_k_meetings,
        ).results
        chunks = self.search_chunks(
            payload.user_external_id,
            payload.question,
            self.settings.query_top_k_chunks,
        ).results
        decisions = self.get_decisions(
            payload.user_external_id,
            payload.question,
            self.settings.query_top_k_decisions,
        ).results

        meeting_ids = {meeting.meeting_id for meeting in meetings}
        meeting_ids.update(chunk.meeting_id for chunk in chunks)
        meeting_ids.update(decision.meeting_id for decision in decisions)

        tasks: list[MeetingTask] = []
        for meeting_id in meeting_ids:
            tasks.extend(self.get_meeting_tasks(meeting_id).tasks)

        answer, citations = self.answerer.answer(
            RetrievalContext(
                question=payload.question,
                meetings=meetings,
                chunks=chunks,
                decisions=decisions,
            )
        )

        return QueryResponse(
            answer=answer,
            citations=citations,
            meetings=meetings,
            chunks=chunks,
            tasks=tasks,
            decisions=decisions,
        )
