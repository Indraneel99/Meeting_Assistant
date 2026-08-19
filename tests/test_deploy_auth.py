from pathlib import Path


def test_deploy_auth_env_example_contains_login_oauth_settings() -> None:
    content = Path("deploy/.env.prod.example").read_text(encoding="utf-8")
    assert "AUTH_PASSWORD_LOGIN_ENABLED=true" in content
    assert "AUTH_GOOGLE_LOGIN_ENABLED=true" in content
    assert "AUTH_LOGIN_ALLOW_DEV=false" in content
    assert "AUTH_GOOGLE_LOGIN_CLIENT_ID=" in content
    assert "GCP_AUTH_GOOGLE_LOGIN_CLIENT_SECRET=" in content
    assert "AUTH_GOOGLE_LOGIN_REDIRECT_BASE=" in content
    assert "Ops / Postman / scripts only" in content


def test_makefile_wires_google_login_auth_settings() -> None:
    content = Path("Makefile").read_text(encoding="utf-8")
    assert "AUTH_PASSWORD_LOGIN_ENABLED ?=" in content
    assert "AUTH_GOOGLE_LOGIN_ENABLED ?=" in content
    assert "AUTH_GOOGLE_LOGIN_CLIENT_ID ?=" in content
    assert "GCP_AUTH_GOOGLE_LOGIN_CLIENT_SECRET ?=" in content
    assert "MEETING_ASSISTANT_AUTH_PASSWORD_LOGIN_ENABLED=$(AUTH_PASSWORD_LOGIN_ENABLED)" in content
    assert "MEETING_ASSISTANT_AUTH_GOOGLE_LOGIN_CLIENT_SECRET=$(GCP_AUTH_GOOGLE_LOGIN_CLIENT_SECRET)" in content
