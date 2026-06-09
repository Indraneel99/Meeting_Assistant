from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from meeting_assistant.core.config import Settings

limiter = Limiter(key_func=get_remote_address, default_limits=[], enabled=False)


def configure_limiter(settings: Settings) -> Limiter:
    limiter.enabled = settings.rate_limit_enabled
    limiter._default_limits = [settings.rate_limit_default] if settings.rate_limit_enabled else []
    return limiter
