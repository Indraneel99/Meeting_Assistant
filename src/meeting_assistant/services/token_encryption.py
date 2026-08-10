from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from meeting_assistant.core.config import Settings

# Local-dev only. Production must set MEETING_ASSISTANT_INTEGRATIONS_ENCRYPTION_KEY.
_DEV_ENCRYPTION_KEY = "V4uLPuCqppf5YJdLGcBoQBGJjjPQd87l2E2vR2JPPDo="


class TokenEncryptor:
    def __init__(self, key: str | bytes) -> None:
        encoded_key = key.encode("utf-8") if isinstance(key, str) else key
        self._fernet = Fernet(encoded_key)

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None:
            return None
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str | None) -> str | None:
        if ciphertext is None:
            return None
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Invalid or corrupted integration token ciphertext") from exc


def build_token_encryptor(settings: Settings) -> TokenEncryptor:
    key = settings.integrations_encryption_key or _DEV_ENCRYPTION_KEY
    return TokenEncryptor(key)
