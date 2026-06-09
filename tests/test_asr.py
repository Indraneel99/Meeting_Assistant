from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from meeting_assistant.core.config import Settings
from meeting_assistant.services.asr import (
    ASRError,
    ASRErrorCode,
    BatchASRAdapter,
    GcsAudioSourceResolver,
    LocalAudioSourceResolver,
    OpenAIHostedASRClient,
    S3AudioSourceResolver,
    build_asr,
    map_http_error_to_asr_error,
    validate_audio_asset,
    AudioAsset,
)


def test_manual_transcript_path_returns_structured_document() -> None:
    adapter = BatchASRAdapter(
        source_resolver=LocalAudioSourceResolver(httpx.Client()),
        transcriber=OpenAIHostedASRClient(
            api_key="test",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-transcribe-diarize",
            language="en",
            chunking_strategy="auto",
            http_client=httpx.Client(),
        ),
    )

    transcript = adapter.transcribe(source_uri=None, transcript_text="Decision: ship it.")

    assert transcript.provider == "manual"
    assert transcript.model_name == "manual-input"
    assert transcript.rendered_text() == "Decision: ship it."
    assert len(transcript.segments) == 1


def test_openai_hosted_transcription_for_local_file(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(b"fake-waveform")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "text": "Hello team. We are shipping tomorrow.",
                "language": "en",
                "duration": 12.5,
                "task": "transcribe",
                "usage": {"type": "duration", "seconds": 12.5},
                "segments": [
                    {"id": "seg-1", "speaker": "A", "start": 0.0, "end": 4.8, "text": "Hello team."},
                    {
                        "id": "seg-2",
                        "speaker": "B",
                        "start": 4.8,
                        "end": 12.5,
                        "text": "We are shipping tomorrow.",
                    },
                ],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = BatchASRAdapter(
        source_resolver=LocalAudioSourceResolver(http_client),
        transcriber=OpenAIHostedASRClient(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-transcribe-diarize",
            language="en",
            chunking_strategy="auto",
            http_client=http_client,
        ),
    )

    transcript = adapter.transcribe(source_uri=str(audio_path), transcript_text=None)

    assert transcript.provider == "openai"
    assert transcript.language == "en"
    assert transcript.duration_seconds == 12.5
    assert transcript.rendered_text() == "A: Hello team.\nB: We are shipping tomorrow."
    assert [segment.speaker for segment in transcript.segments] == ["A", "B"]


def test_validate_audio_asset_rejects_empty_content() -> None:
    with pytest.raises(ASRError) as exc_info:
        validate_audio_asset(
            AudioAsset(filename="meeting.wav", content=b"", content_type="audio/wav", source_uri="file:///tmp/x.wav")
        )

    assert exc_info.value.code == ASRErrorCode.EMPTY_AUDIO


def test_validate_audio_asset_rejects_unsupported_format() -> None:
    with pytest.raises(ASRError) as exc_info:
        validate_audio_asset(
            AudioAsset(filename="notes.txt", content=b"hello", content_type="text/plain", source_uri="file:///tmp/x.txt")
        )

    assert exc_info.value.code == ASRErrorCode.UNSUPPORTED_FORMAT


def test_map_http_error_to_asr_error_maps_quota_exceeded() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    response = httpx.Response(429, request=request, json={"error": {"message": "Rate limit exceeded"}})
    error = map_http_error_to_asr_error(httpx.HTTPStatusError("quota", request=request, response=response), provider="openai")

    assert error.code == ASRErrorCode.QUOTA_EXCEEDED


def test_s3_audio_source_resolver_reads_object() -> None:
    client = MagicMock()
    client.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=b"audio-bytes")),
        "ContentType": "audio/wav",
    }
    resolver = S3AudioSourceResolver(default_bucket="recordings", client=client)

    asset = resolver.resolve("s3://recordings/meetings/sync.wav")

    assert asset.content == b"audio-bytes"
    assert asset.filename == "sync.wav"
    client.get_object.assert_called_once_with(Bucket="recordings", Key="meetings/sync.wav")


def test_gcs_audio_source_resolver_reads_object() -> None:
    storage_module = MagicMock()
    blob = MagicMock()
    blob.exists.return_value = True
    blob.download_as_bytes.return_value = b"gcs-audio"
    blob.content_type = "audio/mpeg"
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket

    resolver = GcsAudioSourceResolver(default_bucket="recordings", client=client)
    asset = resolver.resolve("gs://recordings/meetings/sync.mp3")

    assert asset.content == b"gcs-audio"
    assert asset.filename == "sync.mp3"


def test_build_asr_uses_openai_provider() -> None:
    asr = build_asr(Settings(asr_provider="openai"))
    assert isinstance(asr, BatchASRAdapter)


def test_missing_transcript_source_raises_structured_error() -> None:
    adapter = build_asr(Settings(asr_provider="openai"))

    with pytest.raises(ASRError) as exc_info:
        adapter.transcribe(source_uri=None, transcript_text=None)

    assert exc_info.value.code == ASRErrorCode.MISSING_SOURCE
