from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx


@dataclass(slots=True)
class AudioAsset:
    filename: str
    content: bytes
    content_type: str
    source_uri: str


@dataclass(slots=True)
class TranscriptSegmentData:
    text: str
    speaker: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    confidence: float | None = None


@dataclass(slots=True)
class TranscriptDocument:
    text: str
    provider: str
    model_name: str
    source_uri: str | None = None
    language: str | None = None
    duration_seconds: float | None = None
    segments: list[TranscriptSegmentData] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def rendered_text(self) -> str:
        if not self.segments:
            return self.text.strip()

        lines = []
        for segment in self.segments:
            prefix = f"{segment.speaker}: " if segment.speaker else ""
            lines.append(f"{prefix}{segment.text.strip()}".strip())
        return "\n".join(line for line in lines if line).strip()


class LocalAudioSourceResolver:
    def __init__(self, http_client: httpx.Client) -> None:
        self.http_client = http_client

    def resolve(self, source_uri: str) -> AudioAsset:
        parsed = urlparse(source_uri)

        if parsed.scheme in {"http", "https"}:
            response = self.http_client.get(source_uri)
            response.raise_for_status()
            return AudioAsset(
                filename=Path(parsed.path or "audio.bin").name or "audio.bin",
                content=response.content,
                content_type=response.headers.get("content-type", "application/octet-stream"),
                source_uri=source_uri,
            )

        if parsed.scheme == "file":
            path = Path(parsed.path)
        else:
            path = Path(source_uri)

        if not path.exists():
            raise ValueError(f"Audio source not found: {source_uri}")

        return AudioAsset(
            filename=path.name,
            content=path.read_bytes(),
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            source_uri=source_uri,
        )


class OpenAIHostedASRClient:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        model_name: str,
        language: str | None,
        chunking_strategy: str,
        http_client: httpx.Client,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.language = language
        self.chunking_strategy = chunking_strategy
        self.http_client = http_client

    def transcribe(self, asset: AudioAsset) -> TranscriptDocument:
        if not self.api_key:
            raise ValueError(
                "MEETING_ASSISTANT_ASR_OPENAI_API_KEY is required when transcribing from source_uri."
            )

        data = {
            "model": self.model_name,
            "response_format": "diarized_json",
            "chunking_strategy": self.chunking_strategy,
        }
        if self.language:
            data["language"] = self.language

        response = self.http_client.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            data=data,
            files={"file": (asset.filename, asset.content, asset.content_type)},
        )
        response.raise_for_status()
        payload = response.json()

        segments = [
            TranscriptSegmentData(
                text=segment.get("text", "").strip(),
                speaker=segment.get("speaker"),
                start_seconds=segment.get("start"),
                end_seconds=segment.get("end"),
            )
            for segment in payload.get("segments", [])
            if segment.get("text")
        ]

        return TranscriptDocument(
            text=payload.get("text", "").strip(),
            provider="openai",
            model_name=self.model_name,
            source_uri=asset.source_uri,
            language=payload.get("language") or self.language,
            duration_seconds=payload.get("duration"),
            segments=segments,
            metadata={
                "task": payload.get("task"),
                "usage": payload.get("usage"),
            },
        )


class BatchASRAdapter:
    """Hybrid ASR adapter.

    Transcript text can be passed directly during development, while uploaded audio
    is transcribed through a hosted provider. The hosted provider can later be
    swapped with a self-hosted Whisper pipeline without changing callers.
    """

    def __init__(self, source_resolver: LocalAudioSourceResolver, hosted_client: OpenAIHostedASRClient) -> None:
        self.source_resolver = source_resolver
        self.hosted_client = hosted_client

    def transcribe(self, source_uri: str | None, transcript_text: str | None) -> TranscriptDocument:
        if transcript_text:
            text = transcript_text.strip()
            return TranscriptDocument(
                text=text,
                provider="manual",
                model_name="manual-input",
                source_uri=source_uri,
                segments=[TranscriptSegmentData(text=text)],
                metadata={"mode": "manual"},
            )
        if source_uri:
            asset = self.source_resolver.resolve(source_uri)
            return self.hosted_client.transcribe(asset)
        raise ValueError("Missing transcript source.")
