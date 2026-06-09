from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from meeting_assistant.core.config import Settings
from meeting_assistant.services.asr import (
    ASRError,
    ASRErrorCode,
    BatchASRAdapter,
    LocalAudioSourceResolver,
    OpenAITranscriber,
)
from meeting_assistant.services.audio_storage import LocalAudioUploadStore, S3AudioUploadStore, validate_upload


def test_local_audio_upload_store_returns_file_uri(tmp_path: Path) -> None:
    store = LocalAudioUploadStore(tmp_path / "audio")
    source_uri = store.store("meeting.wav", b"audio-bytes", "audio/wav")

    assert source_uri.startswith("file://")
    assert Path(source_uri.replace("file://", "")).exists()


def test_s3_audio_upload_store_returns_s3_uri() -> None:
    client = MagicMock()
    store = S3AudioUploadStore(bucket="recordings", prefix="audio/", client=client)

    source_uri = store.store("meeting.wav", b"audio-bytes", "audio/wav")

    assert source_uri.startswith("s3://recordings/audio/")
    client.put_object.assert_called_once()


def test_validate_upload_rejects_oversized_file() -> None:
    with pytest.raises(ASRError) as exc_info:
        validate_upload("meeting.wav", b"x" * 10, "audio/wav", max_bytes=5)

    assert exc_info.value.code == ASRErrorCode.UNSUPPORTED_FORMAT


def test_async_upload_failure_marks_workflow_failed(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from meeting_assistant.api import app as app_module
    from meeting_assistant.api.app import create_app

    upload_dir = tmp_path / "uploads"
    settings = Settings(
        asr_upload_dir=str(upload_dir),
        batch_processing_mode="async",
        job_queue_provider="inprocess",
        queue_provider="memory",
    )

    failing_asr = BatchASRAdapter(
        source_resolver=LocalAudioSourceResolver(httpx.Client()),
        transcriber=OpenAITranscriber(
            api_key=None,
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-transcribe-diarize",
            language="en",
            chunking_strategy="auto",
            http_client=httpx.Client(),
        ),
    )

    original_bootstrap = app_module.bootstrap_container

    def patched_bootstrap(app_settings=None):
        container = original_bootstrap(app_settings or settings)
        container.orchestrator.asr = failing_asr
        return container

    monkeypatch.setattr(app_module, "bootstrap_container", patched_bootstrap)

    with TestClient(create_app(settings)) as client:
        accepted = client.post(
            "/api/v1/meetings/batch/upload",
            data={
                "user_external_id": f"user-{uuid4()}",
                "user_email": f"{uuid4()}@example.com",
                "title": "Async audio failure",
            },
            files={"audio": ("meeting.wav", b"fake-waveform", "audio/wav")},
        )
        assert accepted.status_code == 202
        workflow_run_id = accepted.json()["workflow_run_id"]

        import time

        terminal_status = None
        for _ in range(100):
            status_response = client.get(f"/api/v1/workflows/{workflow_run_id}")
            terminal_status = status_response.json()["status"]
            if terminal_status == "failed":
                break
            time.sleep(0.05)

        assert terminal_status == "failed"
        failure_reason = client.get(f"/api/v1/workflows/{workflow_run_id}").json()["failure_reason"]
        assert "missing_credentials" in failure_reason
