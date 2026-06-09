import pytest
from fastapi.testclient import TestClient

from meeting_assistant.api.app import create_app
from meeting_assistant.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_enabled=False, rate_limit_enabled=False)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
