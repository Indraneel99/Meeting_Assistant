from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class PubSubPushMessage(BaseModel):
    data: str
    attributes: dict[str, str] = Field(default_factory=dict)
    message_id: str | None = Field(default=None, alias="messageId")
    publish_time: str | None = Field(default=None, alias="publishTime")


class PubSubPushEnvelope(BaseModel):
    message: PubSubPushMessage
    subscription: str | None = None


def decode_pubsub_push_envelope(envelope: PubSubPushEnvelope) -> tuple[int, dict[str, Any], dict[str, str]]:
    try:
        raw = base64.b64decode(envelope.message.data, validate=True)
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid pubsub message data") from exc

    workflow_run_id = parsed.get("workflow_run_id")
    payload = parsed.get("payload")
    if not isinstance(workflow_run_id, int) or not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="pubsub message must include workflow_run_id and payload")

    return workflow_run_id, payload, envelope.message.attributes


def verify_pubsub_push_authorization(
    authorization: str | None,
    *,
    audience: str | None,
    skip_auth: bool,
) -> None:
    if skip_auth:
        return
    if not audience:
        raise HTTPException(status_code=500, detail="pubsub push audience is not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing pubsub push bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing pubsub push bearer token")

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid pubsub push token") from exc
