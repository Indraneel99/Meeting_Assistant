from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import IntegrationProvider, IntegrationStatus, UserIntegration
from meeting_assistant.db.session import initialize_database
from meeting_assistant.repositories import Repository
from meeting_assistant.services.token_encryption import TokenEncryptor, build_token_encryptor


@pytest.fixture
def integration_db(tmp_path: Path) -> tuple[str, sessionmaker[Session]]:
    database_url = f"sqlite:///{tmp_path / 'integrations.db'}"
    initialize_database(database_url)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    return database_url, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture
def encryptor() -> TokenEncryptor:
    return TokenEncryptor(Fernet.generate_key().decode())


def test_token_encryptor_roundtrip(encryptor: TokenEncryptor) -> None:
    assert encryptor.decrypt(encryptor.encrypt("xoxb-secret")) == "xoxb-secret"
    assert encryptor.encrypt(None) is None
    assert encryptor.decrypt(None) is None


def test_token_encryptor_rejects_invalid_ciphertext(encryptor: TokenEncryptor) -> None:
    with pytest.raises(ValueError, match="Invalid or corrupted"):
        encryptor.decrypt("not-valid-ciphertext")


def test_build_token_encryptor_uses_settings_key() -> None:
    key = Fernet.generate_key().decode()
    settings = Settings(integrations_encryption_key=key)
    encryptor = build_token_encryptor(settings)
    assert encryptor.decrypt(encryptor.encrypt("token")) == "token"


def test_user_integrations_migration_creates_table(integration_db: tuple[str, sessionmaker[Session]]) -> None:
    database_url, _ = integration_db
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    inspector = inspect(engine)
    assert "user_integrations" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("user_integrations")}
    assert {
        "user_id",
        "provider",
        "status",
        "access_token_enc",
        "refresh_token_enc",
        "settings_json",
        "provider_account_id",
    }.issubset(columns)


def test_upsert_stores_encrypted_tokens(
    integration_db: tuple[str, sessionmaker[Session]],
    encryptor: TokenEncryptor,
) -> None:
    _, session_factory = integration_db
    repository = Repository(session_factory)
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")

    integration = repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.SLACK,
        provider_account_id="T123",
        access_token="xoxb-access",
        refresh_token="xoxr-refresh",
        scopes='["chat:write"]',
        settings_json={"channels": ["#product"]},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert integration.status == IntegrationStatus.CONNECTED
    assert integration.settings_json == {"channels": ["#product"]}
    assert integration.access_token_enc != "xoxb-access"
    assert integration.refresh_token_enc != "xoxr-refresh"

    access, refresh = repository.decrypt_integration_tokens(integration, encryptor=encryptor)
    assert access == "xoxb-access"
    assert refresh == "xoxr-refresh"


def test_upsert_updates_existing_integration(
    integration_db: tuple[str, sessionmaker[Session]],
    encryptor: TokenEncryptor,
) -> None:
    _, session_factory = integration_db
    repository = Repository(session_factory)
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")

    first = repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.GOOGLE,
        provider_account_id="sub-1",
        access_token="old-token",
    )
    second = repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.GOOGLE,
        provider_account_id="sub-1",
        access_token="new-token",
        settings_json={"invite_email": "alice@example.com"},
    )

    assert second.id == first.id
    access, _ = repository.decrypt_integration_tokens(second, encryptor=encryptor)
    assert access == "new-token"
    assert second.settings_json == {"invite_email": "alice@example.com"}


def test_list_and_get_user_integrations(
    integration_db: tuple[str, sessionmaker[Session]],
    encryptor: TokenEncryptor,
) -> None:
    _, session_factory = integration_db
    repository = Repository(session_factory)
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")

    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.SLACK,
        provider_account_id="T123",
        access_token="slack-token",
    )
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.EMAIL_PREFS,
        provider_account_id="",
        settings_json={"notification_emails": ["alice@example.com"]},
    )

    integrations = repository.list_user_integrations(user.id)
    assert {item.provider for item in integrations} == {
        IntegrationProvider.SLACK,
        IntegrationProvider.EMAIL_PREFS,
    }

    slack = repository.get_user_integration(user.id, IntegrationProvider.SLACK, provider_account_id="T123")
    assert slack is not None
    assert slack.provider_account_id == "T123"


def test_update_settings_and_revoke(
    integration_db: tuple[str, sessionmaker[Session]],
    encryptor: TokenEncryptor,
) -> None:
    _, session_factory = integration_db
    repository = Repository(session_factory)
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")

    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.EMAIL_PREFS,
        access_token="unused",
        settings_json={"notification_emails": ["alice@example.com"]},
    )

    updated = repository.update_user_integration_settings(
        user.id,
        IntegrationProvider.EMAIL_PREFS,
        {"notification_emails": ["alice@example.com", "bob@example.com"]},
    )
    assert updated.settings_json == {"notification_emails": ["alice@example.com", "bob@example.com"]}

    revoked = repository.revoke_user_integration(user.id, IntegrationProvider.EMAIL_PREFS)
    assert revoked.status == IntegrationStatus.REVOKED
    assert revoked.access_token_enc is None
    assert revoked.refresh_token_enc is None


def test_unique_constraint_on_user_provider_account(
    integration_db: tuple[str, sessionmaker[Session]],
    encryptor: TokenEncryptor,
) -> None:
    _, session_factory = integration_db
    repository = Repository(session_factory)
    user = repository.get_or_create_user(f"user-{uuid4()}", f"{uuid4()}@example.com")

    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.SLACK,
        provider_account_id="T123",
        access_token="token-1",
    )

    with session_factory() as session, pytest.raises(IntegrityError):
        session.add(
            UserIntegration(
                user_id=user.id,
                provider=IntegrationProvider.SLACK,
                provider_account_id="T123",
                status=IntegrationStatus.CONNECTED,
                connected_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
