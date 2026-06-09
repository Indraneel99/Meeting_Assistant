from fastapi import APIRouter, Depends

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.schemas.retrieval import (
    MeetingTasksResponse,
    PaginatedChunkSearchResponse,
    PaginatedDecisionsResponse,
    PaginatedSearchMeetingsResponse,
    QueryRequest,
    QueryResponse,
)

router = APIRouter(tags=["retrieval"])


@router.post("/query", response_model=QueryResponse)
def answer_query(
    payload: QueryRequest,
    container: Container = Depends(get_container),
) -> QueryResponse:
    return container.query_service.answer(payload)


@router.get("/meetings/search", response_model=PaginatedSearchMeetingsResponse)
def search_past_meetings(
    user_external_id: str,
    query: str,
    limit: int = 5,
    cursor: str | None = None,
    container: Container = Depends(get_container),
) -> PaginatedSearchMeetingsResponse:
    return container.query_service.search_past_meetings(
        user_external_id,
        query,
        limit,
        cursor=cursor,
    )


@router.get("/meetings/chunks/search", response_model=PaginatedChunkSearchResponse)
def search_meeting_chunks(
    user_external_id: str,
    query: str,
    limit: int = 5,
    cursor: str | None = None,
    container: Container = Depends(get_container),
) -> PaginatedChunkSearchResponse:
    return container.query_service.search_chunks(
        user_external_id,
        query,
        limit,
        cursor=cursor,
    )


@router.get("/meetings/{meeting_id}/tasks", response_model=MeetingTasksResponse)
def get_meeting_tasks(
    meeting_id: int,
    container: Container = Depends(get_container),
) -> MeetingTasksResponse:
    return container.query_service.get_meeting_tasks(meeting_id)


@router.get("/decisions", response_model=PaginatedDecisionsResponse)
def get_decisions(
    user_external_id: str,
    topic: str,
    limit: int = 5,
    cursor: str | None = None,
    container: Container = Depends(get_container),
) -> PaginatedDecisionsResponse:
    return container.query_service.get_decisions(
        user_external_id,
        topic,
        limit,
        cursor=cursor,
    )
