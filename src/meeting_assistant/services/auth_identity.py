from __future__ import annotations

from uuid import uuid4


def normalize_auth_email(email: str) -> str:
    return email.strip().lower()


def generate_user_external_id() -> str:
    return f"usr_{uuid4().hex[:16]}"
