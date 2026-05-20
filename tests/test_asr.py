from pathlib import Path

import httpx

from meeting_assistant.services.asr import BatchASRAdapter, LocalAudioSourceResolver, OpenAIHostedASRClient


def test_manual_transcript_path_returns_structured_document() -> None:
    adapter = BatchASRAdapter(
        source_resolver=LocalAudioSourceResolver(httpx.Client()),
        hosted_client=OpenAIHostedASRClient(
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
        hosted_client=OpenAIHostedASRClient(
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
