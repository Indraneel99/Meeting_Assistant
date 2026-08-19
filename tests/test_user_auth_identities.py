from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from meeting_assistant.db.models import AuthProvider, UserAuthIdentity
from meeting_assistant.db.session import initialize_database
from meeting_assistant.repositories import Repository
from meeting_assistant.services.auth_identity import normalize_auth_email


@pytest.fixture
def auth_db(tmp_path: Path) -> tuple[str, sessionmaker[Session]]:
    database_url = f"sqlite:///{tmp_path / 'auth_identities.db'}"
    initialize_database(database_url)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    return database_url, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_user_auth_identities_migration_creates_table(auth_db: tuple[str, sessionmaker[Session]]) -> None:
    database_url, _ = auth_db
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    inspector = inspect(engine)
    assert "user_auth_identities" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("user_auth_identities")}
    assert {
        "user_id",
        "provider",
        "provider_subject",
        "password_hash",
        "metadata_json",
    }.issubset(columns)


def test_create_user_with_email_password_identity(auth_db: tuple[str, sessionmaker[Session]]) -> None:
    _, session_factory = auth_db
    repository = Repository(session_factory)
    email = f"alice-{uuid4()}@example.com"
    normalized = normalize_auth_email(email)

    user, identity = repository.create_user_with_auth_identity(
        email=email,
        provider=AuthProvider.EMAIL_PASSWORD,
        provider_subject=normalized,
        password_hash="$2b$12$hashed",
        metadata_json={"display_name": "Alice"},
    )

    assert user.email == normalized
    assert user.external_id != normalized
    assert user.external_id.startswith("usr_")
    assert identity.provider == AuthProvider.EMAIL_PASSWORD
    assert identity.provider_subject == normalized
    assert identity.password_hash == "$2b$12$hashed"
    assert identity.metadata_json == {"display_name": "Alice"}


def test_get_auth_identity_by_provider_subject(auth_db: tuple[str, sessionmaker[Session]]) -> None:
    _, session_factory = auth_db
    repository = Repository(session_factory)
    email = f"bob-{uuid4()}@example.com"
    normalized = normalize_auth_email(email)

    repository.create_user_with_auth_identity(
        email=email,
        provider=AuthProvider.EMAIL_PASSWORD,
        provider_subject=normalized,
        password_hash="hash",
    )

    found = repository.get_auth_identity(AuthProvider.EMAIL_PASSWORD, normalized)
    assert found is not None
    assert found.provider_subject == normalized


def test_get_user_by_email_is_case_insensitive(auth_db: tuple[str, sessionmaker[Session]]) -> None:
    _, session_factory = auth_db
    repository = Repository(session_factory)
    email = f"Carol-{uuid4()}@Example.COM"

    created, _ = repository.create_user_with_auth_identity(
        email=email,
        provider=AuthProvider.EMAIL_PASSWORD,
        provider_subject=normalize_auth_email(email),
    )

    found = repository.get_user_by_email(email.upper())
    assert found is not None
    assert found.id == created.id
    assert found.email == normalize_auth_email(email)


def test_link_google_identity_to_existing_user(auth_db: tuple[str, sessionmaker[Session]]) -> None:
    _, session_factory = auth_db
    repository = Repository(session_factory)
    email = f"dana-{uuid4()}@example.com"
    google_sub = f"google-sub-{uuid4()}"

    user, email_identity = repository.create_user_with_auth_identity(
        email=email,
        provider=AuthProvider.EMAIL_PASSWORD,
        provider_subject=normalize_auth_email(email),
        password_hash="hash",
    )

    google_identity = repository.link_auth_identity_to_user(
        user.id,
        provider=AuthProvider.GOOGLE,
        provider_subject=google_sub,
        metadata_json={"name": "Dana"},
    )

    assert google_identity.user_id == user.id
    assert google_identity.provider == AuthProvider.GOOGLE
    assert google_identity.provider_subject == google_sub

    identities = repository.list_auth_identities_for_user(user.id)
    assert {item.provider for item in identities} == {AuthProvider.EMAIL_PASSWORD, AuthProvider.GOOGLE}
    assert email_identity.id != google_identity.id


def test_unique_constraint_on_provider_subject(auth_db: tuple[str, sessionmaker[Session]]) -> None:
    _, session_factory = auth_db
    repository = Repository(session_factory)
    email = f"eve-{uuid4()}@example.com"
    normalized = normalize_auth_email(email)

    repository.create_user_with_auth_identity(
        email=email,
        provider=AuthProvider.EMAIL_PASSWORD,
        provider_subject=normalized,
        password_hash="hash-1",
    )

    with session_factory() as session, pytest.raises(IntegrityError):
        other_user = repository.get_or_create_user(f"other-{uuid4()}", f"other-{uuid4()}@example.com")
        session.add(
            UserAuthIdentity(
                user_id=other_user.id,
                provider=AuthProvider.EMAIL_PASSWORD,
                provider_subject=normalized,
                password_hash="hash-2",
            )
        )
        session.commit()
