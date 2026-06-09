from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import EmailStr

from meeting_assistant.api.auth import assert_user_scope
from meeting_assistant.api.deps import get_container, get_principal
from meeting_assistant.api.rate_limit import limiter
from meeting_assistant.container import Container
from meeting_assistant.schemas.batch import BatchJobAcceptedResponse, BatchMeetingRequest, BatchMeetingResponse
from meeting_assistant.services.asr import ASRError
from meeting_assistant.services.audio_storage import validate_upload

router = APIRouter(tags=["batch"])


def _submit_batch(
    payload: BatchMeetingRequest,
    response: Response,
    container: Container,
) -> BatchMeetingResponse | BatchJobAcceptedResponse:
    try:
        result = container.orchestrator.submit_batch_meeting(payload)
    except ASRError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if container.settings.batch_processing_mode == "async":
        response.status_code = 202
        return BatchJobAcceptedResponse.model_validate(result)

    return BatchMeetingResponse.model_validate(result)


@router.post("/meetings/batch", response_model=BatchMeetingResponse | BatchJobAcceptedResponse)
@limiter.limit("10/minute")
def ingest_batch_meeting(
    request: Request,
    payload: BatchMeetingRequest,
    response: Response,
    container: Container = Depends(get_container),
) -> BatchMeetingResponse | BatchJobAcceptedResponse:
    assert_user_scope(get_principal(request), payload.user_external_id)
    return _submit_batch(payload, response, container)


@router.post("/meetings/batch/upload", response_model=BatchMeetingResponse | BatchJobAcceptedResponse)
@limiter.limit("10/minute")
async def ingest_batch_meeting_upload(
    request: Request,
    response: Response,
    user_external_id: str = Form(..., min_length=1),
    user_email: EmailStr = Form(...),
    title: str = Form(..., min_length=1),
    audio: UploadFile = File(...),
    container: Container = Depends(get_container),
) -> BatchMeetingResponse | BatchJobAcceptedResponse:
    assert_user_scope(get_principal(request), user_external_id)
    content = await audio.read()
    filename = audio.filename or "audio.bin"
    content_type = audio.content_type or "application/octet-stream"

    try:
        validate_upload(
            filename,
            content,
            content_type,
            max_bytes=container.settings.asr_max_upload_bytes,
        )
        source_uri = container.audio_upload_store.store(filename, content, content_type)
    except ASRError as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc

    payload = BatchMeetingRequest(
        user_external_id=user_external_id,
        user_email=user_email,
        title=title,
        source_uri=source_uri,
        transcript_text=None,
    )
    return _submit_batch(payload, response, container)
