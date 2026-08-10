from __future__ import annotations

import ssl
from typing import Any

import redis


def redis_from_url(redis_url: str, *, decode_responses: bool | None = None) -> redis.Redis:
    """Build a sync Redis client. Upstash requires TLS via rediss://."""
    kwargs: dict[str, Any] = {}
    if redis_url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
    if decode_responses is not None:
        kwargs["decode_responses"] = decode_responses
    return redis.from_url(redis_url, **kwargs)
