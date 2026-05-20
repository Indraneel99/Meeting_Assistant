from fastapi import APIRouter, Depends

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.schemas.retrieval import (
    DecisionsResponse,
    MeetingTasksResponse,
    QueryRequest,
    QueryResponse,
    SearchMeetingsResponse,
)

router = APIRouter(tags=["retrieval"])


@router.post("/query", response_model=QueryResponse)
def answer_query(
    payload: QueryRequest,
    container: Container = Depends(get_container),
) -> QueryResponse:
    return container.query_service.answer(payload)


@router.get("/meetings/search", response_model=SearchMeetingsResponse)
def search_past_meetings(
    user_external_id: str,
    query: str,
    limit: int = 5,
    container: Container = Depends(get_container),
) -> SearchMeetingsResponse:
    return container.query_service.search_past_meetings(user_external_id, query, limit)


@router.get("/meetings/{meeting_id}/tasks", response_model=MeetingTasksResponse)
def get_meeting_tasks(
    meeting_id: int,
    container: Container = Depends(get_container),
) -> MeetingTasksResponse:
    return container.query_service.get_meeting_tasks(meeting_id)


@router.get("/decisions", response_model=DecisionsResponse)
def get_decisions(
    user_external_id: str,
    topic: str,
    limit: int = 5,
    container: Container = Depends(get_container),
) -> DecisionsResponse:
    return container.query_service.get_decisions(user_external_id, topic, limit)
