from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings
from meeting_assistant.services.asr import BatchASRAdapter, LocalAudioSourceResolver, OpenAITranscriber


def test_batch_upload_endpoint_runs_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    upload_dir = tmp_path / "uploads"
    settings = Settings(asr_upload_dir=str(upload_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "text": "Decision: ship the audio upload path. Action: send recap.",
                "language": "en",
                "duration": 8.0,
                "segments": [
                    {
                        "speaker": "A",
                        "start": 0.0,
                        "end": 8.0,
                        "text": "Decision: ship the audio upload path. Action: send recap.",
                    }
                ],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    asr = BatchASRAdapter(
        source_resolver=LocalAudioSourceResolver(http_client),
        transcriber=OpenAITranscriber(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-transcribe-diarize",
            language="en",
            chunking_strategy="auto",
            http_client=http_client,
        ),
    )

    from meeting_assistant.api import app as app_module

    original_bootstrap = app_module.bootstrap_container

    def patched_bootstrap(app_settings=None):
        container = original_bootstrap(app_settings or settings)
        container.orchestrator.asr = asr
        return container

    monkeypatch.setattr(app_module, "bootstrap_container", patched_bootstrap)

    user_external_id = f"user-{uuid4()}"
    user_email = f"{uuid4()}@example.com"

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/meetings/batch/upload",
            data={
                "user_external_id": user_external_id,
                "user_email": user_email,
                "title": "Uploaded audio sync",
            },
            files={"audio": ("meeting.wav", b"fake-waveform", "audio/wav")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] in {"done", "awaiting_approval"}
        assert payload["summary"]
        assert payload["tasks_created"] >= 1

        search = client.get(
            "/api/v1/meetings/search",
            params={"user_external_id": user_external_id, "query": "audio upload", "limit": 5},
        )
        assert search.status_code == 200
        assert len(search.json()["results"]) == 1


def test_batch_upload_rejects_unsupported_format(tmp_path: Path) -> None:
    settings = Settings(asr_upload_dir=str(tmp_path / "uploads"))

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/meetings/batch/upload",
            data={
                "user_external_id": f"user-{uuid4()}",
                "user_email": f"{uuid4()}@example.com",
                "title": "Bad upload",
            },
            files={"audio": ("notes.txt", b"plain text", "text/plain")},
        )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "unsupported_format"
