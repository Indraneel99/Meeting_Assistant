from fastapi import APIRouter, Depends, HTTPException

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.schemas.batch import BatchMeetingRequest, BatchMeetingResponse

router = APIRouter(tags=["batch"])


@router.post("/meetings/batch", response_model=BatchMeetingResponse)
def ingest_batch_meeting(
    payload: BatchMeetingRequest,
    container: Container = Depends(get_container),
) -> BatchMeetingResponse:
    try:
        result = container.orchestrator.process_batch_meeting(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return BatchMeetingResponse.model_validate(result)
