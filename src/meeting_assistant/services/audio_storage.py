from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from meeting_assistant.core.config import Settings
from meeting_assistant.services.asr import ASRError, ASRErrorCode, AudioAsset, validate_audio_asset

logger = logging.getLogger("uvicorn.error")


class AudioUploadStore(Protocol):
    def store(self, filename: str, content: bytes, content_type: str) -> str:
        ...


class LocalAudioUploadStore:
    def __init__(self, upload_dir: Path) -> None:
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def store(self, filename: str, content: bytes, content_type: str) -> str:
        safe_name = f"{uuid4().hex}_{Path(filename).name or 'audio.bin'}"
        path = self.upload_dir / safe_name
        path.write_bytes(content)
        return path.as_uri()


class S3AudioUploadStore:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "audio/",
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix if prefix.endswith("/") or not prefix else f"{prefix}/"
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
                "boto3 is required for S3 audio uploads.",
                details={"install": "pip install boto3"},
            ) from exc
        return boto3.client("s3", region_name=self.region)

    def store(self, filename: str, content: bytes, content_type: str) -> str:
        key = f"{self.prefix}{uuid4().hex}_{Path(filename).name or 'audio.bin'}"
        client = self._get_client()
        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )
        return f"s3://{self.bucket}/{key}"


def validate_upload(filename: str, content: bytes, content_type: str, *, max_bytes: int) -> None:
    if len(content) > max_bytes:
        raise ASRError(
            ASRErrorCode.UNSUPPORTED_FORMAT,
            f"Audio upload exceeds maximum size of {max_bytes} bytes.",
            details={"filename": filename, "size_bytes": len(content), "max_bytes": max_bytes},
        )

    asset = AudioAsset(
        filename=filename or "audio.bin",
        content=content,
        content_type=content_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream",
        source_uri="upload://pending",
    )
    validate_audio_asset(asset)


def build_audio_upload_store(settings: Settings) -> AudioUploadStore:
    if settings.asr_upload_backend == "s3":
        if not settings.asr_s3_bucket:
            raise ValueError("MEETING_ASSISTANT_ASR_S3_BUCKET is required when asr_upload_backend=s3.")
        logger.info("Audio upload backend=s3 bucket=%s", settings.asr_s3_bucket)
        return S3AudioUploadStore(
            bucket=settings.asr_s3_bucket,
            prefix=settings.asr_s3_upload_prefix,
            region=settings.asr_s3_region,
        )

    upload_dir = Path(settings.asr_upload_dir)
    logger.info("Audio upload backend=local dir=%s", upload_dir)
    return LocalAudioUploadStore(upload_dir)
