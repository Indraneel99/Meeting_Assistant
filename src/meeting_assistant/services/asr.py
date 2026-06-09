from __future__ import annotations

import json
import logging
import mimetypes
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from meeting_assistant.core.config import Settings

logger = logging.getLogger("uvicorn.error")

SUPPORTED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".webm",
    ".flac",
    ".mpeg",
    ".mpga",
}
SUPPORTED_AUDIO_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
    "audio/ogg",
    "audio/webm",
    "audio/flac",
}


class ASRErrorCode(StrEnum):
    UNSUPPORTED_FORMAT = "unsupported_format"
    EMPTY_AUDIO = "empty_audio"
    SOURCE_NOT_FOUND = "source_not_found"
    QUOTA_EXCEEDED = "quota_exceeded"
    PROVIDER_ERROR = "provider_error"
    MISSING_CREDENTIALS = "missing_credentials"
    MISSING_SOURCE = "missing_source"


class ASRError(Exception):
    def __init__(
        self,
        code: ASRErrorCode,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }

    def failure_reason(self) -> str:
        return json.dumps(self.to_dict())


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


class AudioSourceResolver(Protocol):
    def resolve(self, source_uri: str) -> AudioAsset:
        ...


class Transcriber(Protocol):
    def transcribe(self, asset: AudioAsset) -> TranscriptDocument:
        ...


class ASRAdapter(Protocol):
    def transcribe(self, source_uri: str | None, transcript_text: str | None) -> TranscriptDocument:
        ...


def validate_audio_asset(asset: AudioAsset, supported_extensions: set[str] | None = None) -> None:
    if not asset.content:
        raise ASRError(
            ASRErrorCode.EMPTY_AUDIO,
            "Audio file is empty.",
            details={"source_uri": asset.source_uri, "filename": asset.filename},
        )

    extensions = supported_extensions or SUPPORTED_AUDIO_EXTENSIONS
    extension = Path(asset.filename).suffix.lower()
    content_type = asset.content_type.split(";", 1)[0].strip().lower()
    if extension not in extensions and content_type not in SUPPORTED_AUDIO_CONTENT_TYPES:
        raise ASRError(
            ASRErrorCode.UNSUPPORTED_FORMAT,
            f"Unsupported audio format: {extension or content_type or 'unknown'}.",
            details={
                "source_uri": asset.source_uri,
                "filename": asset.filename,
                "content_type": asset.content_type,
                "supported_extensions": sorted(extensions),
            },
        )


def map_http_error_to_asr_error(error: httpx.HTTPStatusError, *, provider: str) -> ASRError:
    response = error.response
    status_code = response.status_code
    body: dict[str, object] = {}
    try:
        payload = response.json()
        if isinstance(payload, dict):
            body = payload
    except ValueError:
        body = {"raw": response.text}

    message = str(body.get("error", body.get("message", response.text or "Transcription request failed.")))
    if isinstance(message, dict):
        message = str(message.get("message", message))

    details = {"provider": provider, "status_code": status_code, "response": body}
    lowered = message.lower()

    if status_code == 429 or "quota" in lowered or "rate limit" in lowered:
        return ASRError(ASRErrorCode.QUOTA_EXCEEDED, message, details=details)
    if status_code == 401 or status_code == 403:
        return ASRError(ASRErrorCode.MISSING_CREDENTIALS, message, details=details)
    if status_code == 404:
        return ASRError(ASRErrorCode.SOURCE_NOT_FOUND, message, details=details)
    if status_code == 400 and any(token in lowered for token in ("unsupported", "invalid file", "format")):
        return ASRError(ASRErrorCode.UNSUPPORTED_FORMAT, message, details=details)
    if status_code == 400 and any(token in lowered for token in ("empty", "no audio", "too short")):
        return ASRError(ASRErrorCode.EMPTY_AUDIO, message, details=details)
    return ASRError(ASRErrorCode.PROVIDER_ERROR, message, details=details)


class HttpAudioSourceResolver:
    def __init__(self, http_client: httpx.Client) -> None:
        self.http_client = http_client

    def resolve(self, source_uri: str) -> AudioAsset:
        try:
            response = self.http_client.get(source_uri)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise map_http_error_to_asr_error(exc, provider="http") from exc
        except httpx.RequestError as exc:
            raise ASRError(
                ASRErrorCode.SOURCE_NOT_FOUND,
                f"Unable to fetch audio source: {source_uri}",
                details={"source_uri": source_uri, "error": str(exc)},
            ) from exc

        parsed = urlparse(source_uri)
        filename = Path(parsed.path or "audio.bin").name or "audio.bin"
        return AudioAsset(
            filename=filename,
            content=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            source_uri=source_uri,
        )


class LocalFileAudioSourceResolver:
    def resolve(self, source_uri: str) -> AudioAsset:
        parsed = urlparse(source_uri)
        path = Path(parsed.path) if parsed.scheme == "file" else Path(source_uri)

        if not path.exists():
            raise ASRError(
                ASRErrorCode.SOURCE_NOT_FOUND,
                f"Audio source not found: {source_uri}",
                details={"source_uri": source_uri},
            )

        return AudioAsset(
            filename=path.name,
            content=path.read_bytes(),
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            source_uri=source_uri,
        )


class S3AudioSourceResolver:
    def __init__(
        self,
        *,
        default_bucket: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.default_bucket = default_bucket
        self.region = region
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise ASRError(
                ASRErrorCode.PROVIDER_ERROR,
                "boto3 is required for s3:// source URIs.",
                details={"install": "pip install boto3"},
            ) from exc
        return boto3.client("s3", region_name=self.region)

    def resolve(self, source_uri: str) -> AudioAsset:
        parsed = urlparse(source_uri)
        bucket = parsed.netloc or self.default_bucket
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ASRError(
                ASRErrorCode.SOURCE_NOT_FOUND,
                f"Invalid S3 URI: {source_uri}",
                details={"source_uri": source_uri},
            )

        client = self._get_client()
        try:
            from botocore.exceptions import ClientError
        except ImportError as exc:
            raise ASRError(
                ASRErrorCode.PROVIDER_ERROR,
                "botocore is required for s3:// source URIs.",
            ) from exc

        try:
            response = client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read()
            content_type = response.get("ContentType") or mimetypes.guess_type(key)[0] or "application/octet-stream"
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "ClientError")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                raise ASRError(
                    ASRErrorCode.SOURCE_NOT_FOUND,
                    f"S3 object not found: {source_uri}",
                    details={"source_uri": source_uri, "error_code": error_code},
                ) from exc
            raise ASRError(
                ASRErrorCode.PROVIDER_ERROR,
                f"Failed to read S3 object: {source_uri}",
                details={"source_uri": source_uri, "error_code": error_code},
            ) from exc

        return AudioAsset(
            filename=Path(key).name,
            content=content,
            content_type=content_type,
            source_uri=source_uri,
        )


class GcsAudioSourceResolver:
    def __init__(self, *, default_bucket: str | None = None, client: Any | None = None) -> None:
        self.default_bucket = default_bucket
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise ASRError(
                ASRErrorCode.PROVIDER_ERROR,
                "google-cloud-storage is required for gs:// source URIs.",
                details={"install": "pip install google-cloud-storage"},
            ) from exc
        return storage.Client()

    def resolve(self, source_uri: str) -> AudioAsset:
        parsed = urlparse(source_uri)
        bucket_name = parsed.netloc or self.default_bucket
        blob_name = parsed.path.lstrip("/")
        if not bucket_name or not blob_name:
            raise ASRError(
                ASRErrorCode.SOURCE_NOT_FOUND,
                f"Invalid GCS URI: {source_uri}",
                details={"source_uri": source_uri},
            )

        client = self._get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        if not blob.exists():
            raise ASRError(
                ASRErrorCode.SOURCE_NOT_FOUND,
                f"GCS object not found: {source_uri}",
                details={"source_uri": source_uri},
            )

        content = blob.download_as_bytes()
        content_type = blob.content_type or mimetypes.guess_type(blob_name)[0] or "application/octet-stream"
        return AudioAsset(
            filename=Path(blob_name).name,
            content=content,
            content_type=content_type,
            source_uri=source_uri,
        )


class CompositeAudioSourceResolver:
    def __init__(self, resolvers: dict[str, AudioSourceResolver]) -> None:
        self.resolvers = resolvers

    def resolve(self, source_uri: str) -> AudioAsset:
        parsed = urlparse(source_uri)
        scheme = parsed.scheme.lower() if parsed.scheme else "file"
        if scheme in {"http", "https", "s3", "gs"}:
            resolver = self.resolvers.get(scheme)
        else:
            resolver = self.resolvers.get("file")

        if resolver is None:
            raise ASRError(
                ASRErrorCode.UNSUPPORTED_FORMAT,
                f"Unsupported audio source scheme: {scheme or 'local'}",
                details={"source_uri": source_uri, "scheme": scheme},
            )

        asset = resolver.resolve(source_uri)
        validate_audio_asset(asset)
        return asset


class OpenAITranscriber:
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
            raise ASRError(
                ASRErrorCode.MISSING_CREDENTIALS,
                "MEETING_ASSISTANT_ASR_OPENAI_API_KEY is required when transcribing from source_uri.",
            )

        data = {
            "model": self.model_name,
            "response_format": "diarized_json",
            "chunking_strategy": self.chunking_strategy,
        }
        if self.language:
            data["language"] = self.language

        try:
            response = self.http_client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files={"file": (asset.filename, asset.content, asset.content_type)},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise map_http_error_to_asr_error(exc, provider="openai") from exc
        except httpx.RequestError as exc:
            raise ASRError(
                ASRErrorCode.PROVIDER_ERROR,
                "OpenAI transcription request failed.",
                details={"error": str(exc)},
            ) from exc

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

        if not payload.get("text", "").strip() and not segments:
            raise ASRError(
                ASRErrorCode.EMPTY_AUDIO,
                "Transcription returned no speech content.",
                details={"source_uri": asset.source_uri},
            )

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

    def __init__(self, source_resolver: AudioSourceResolver, transcriber: Transcriber) -> None:
        self.source_resolver = source_resolver
        self.transcriber = transcriber

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
            return self.transcriber.transcribe(asset)
        raise ASRError(
            ASRErrorCode.MISSING_SOURCE,
            "Either source_uri or transcript_text must be provided.",
        )


# Backward-compatible aliases used in tests and older imports.
OpenAIHostedASRClient = OpenAITranscriber


class LocalAudioSourceResolver:
    """Development resolver for HTTP(S) and local filesystem paths."""

    def __init__(self, http_client: httpx.Client) -> None:
        self._resolver = CompositeAudioSourceResolver(
            {
                "http": HttpAudioSourceResolver(http_client),
                "https": HttpAudioSourceResolver(http_client),
                "file": LocalFileAudioSourceResolver(),
            }
        )

    def resolve(self, source_uri: str) -> AudioAsset:
        return self._resolver.resolve(source_uri)


def build_source_resolver(settings: Settings, http_client: httpx.Client) -> AudioSourceResolver:
    resolvers: dict[str, AudioSourceResolver] = {
        "http": HttpAudioSourceResolver(http_client),
        "https": HttpAudioSourceResolver(http_client),
        "file": LocalFileAudioSourceResolver(),
    }
    if settings.asr_s3_bucket:
        resolvers["s3"] = S3AudioSourceResolver(
            default_bucket=settings.asr_s3_bucket,
            region=settings.asr_s3_region,
        )
    if settings.asr_gcs_bucket:
        resolvers["gs"] = GcsAudioSourceResolver(default_bucket=settings.asr_gcs_bucket)
    return CompositeAudioSourceResolver(resolvers)


def build_asr(settings: Settings) -> ASRAdapter:
    http_client = httpx.Client(timeout=settings.asr_openai_timeout_seconds)
    source_resolver = build_source_resolver(settings, http_client)

    if settings.asr_provider == "openai":
        transcriber: Transcriber = OpenAITranscriber(
            api_key=settings.asr_openai_api_key,
            base_url=settings.asr_openai_base_url,
            model_name=settings.asr_openai_model,
            language=settings.asr_openai_language,
            chunking_strategy=settings.asr_openai_chunking_strategy,
            http_client=http_client,
        )
    else:
        raise ValueError(f"Unsupported ASR provider: {settings.asr_provider}")

    logger.info("ASR provider=%s model=%s", settings.asr_provider, settings.asr_openai_model)
    return BatchASRAdapter(source_resolver=source_resolver, transcriber=transcriber)
