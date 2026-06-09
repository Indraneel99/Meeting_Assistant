from fastapi import APIRouter, Depends, HTTPException, Response

from meeting_assistant.api.deps import get_container
from meeting_assistant.container import Container
from meeting_assistant.schemas.batch import BatchJobAcceptedResponse, BatchMeetingRequest, BatchMeetingResponse

router = APIRouter(tags=["batch"])


@router.post("/meetings/batch", response_model=BatchMeetingResponse | BatchJobAcceptedResponse)
def ingest_batch_meeting(
    payload: BatchMeetingRequest,
    response: Response,
    container: Container = Depends(get_container),
) -> BatchMeetingResponse | BatchJobAcceptedResponse:
    try:
        result = container.orchestrator.submit_batch_meeting(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if container.settings.batch_processing_mode == "async":
        response.status_code = 202
        return BatchJobAcceptedResponse.model_validate(result)

    return BatchMeetingResponse.model_validate(result)
