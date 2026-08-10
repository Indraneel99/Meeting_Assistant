from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.yml"
COMPOSE_ENV_EXAMPLE = ROOT / ".env.compose.example"

REQUIRED_SERVICES = ("postgres", "redis", "api", "worker")
REQUIRED_ENV_VARS = (
    "MEETING_ASSISTANT_DATABASE_URL=postgresql+psycopg://meeting_assistant:meeting_assistant@postgres:5432/meeting_assistant",
    "MEETING_ASSISTANT_BATCH_PROCESSING_MODE=async",
    "MEETING_ASSISTANT_JOB_QUEUE_PROVIDER=arq",
    "MEETING_ASSISTANT_QUEUE_PROVIDER=redis",
    "MEETING_ASSISTANT_REDIS_URL=redis://redis:6379/0",
)


def test_docker_compose_file_exists() -> None:
    assert COMPOSE_FILE.is_file()


def test_docker_compose_defines_required_services() -> None:
    content = COMPOSE_FILE.read_text()
    for service in REQUIRED_SERVICES:
        assert f"  {service}:" in content


def test_compose_env_example_documents_stack_settings() -> None:
    content = COMPOSE_ENV_EXAMPLE.read_text()
    for env_line in REQUIRED_ENV_VARS:
        assert env_line in content


def test_docker_compose_config_is_valid() -> None:
    if shutil.which("docker") is None:
        return

    env_file = ROOT / ".env.compose"
    if not env_file.is_file():
        env_file.write_text(COMPOSE_ENV_EXAMPLE.read_text())

    result = subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), "config", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
