from __future__ import annotations

import httpx

from meeting_assistant.services.tools.base import RetryableToolError

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def raise_for_response(response: httpx.Response, *, provider: str) -> None:
    if response.is_success:
        return
    message = _extract_error_message(response)
    if response.status_code in RETRYABLE_STATUS_CODES:
        raise RetryableToolError(f"{provider} request failed with retryable status {response.status_code}: {message}")
    raise RuntimeError(f"{provider} request failed with status {response.status_code}: {message}")


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    **kwargs: object,
) -> dict[str, object]:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        raise RetryableToolError(f"{provider} request failed: {exc}") from exc
    raise_for_response(response, provider=provider)
    if not response.content:
        return {}
    payload = response.json()
    if isinstance(payload, dict):
        return payload
    return {"data": payload}


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("message") or first)
        message = payload.get("message") or payload.get("error")
        if message:
            return str(message)
    return response.text or response.reason_phrase
