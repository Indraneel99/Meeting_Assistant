from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
DEPLOY_ENV_EXAMPLE = ROOT / "deploy" / ".env.prod.example"

PUBSUB_MAKE_TARGETS = (
    "pubsub-topic-create",
    "pubsub-push-sa-create",
    "pubsub-iam",
    "pubsub-subscription-create",
    "pubsub-setup",
)

PUBSUB_ENV_VARS = (
    "JOB_QUEUE_PROVIDER",
    "PUBSUB_TOPIC",
    "PUBSUB_PROJECT",
    "PUBSUB_SUBSCRIPTION",
    "PUBSUB_PUSH_PATH",
    "PUBSUB_PUSH_SERVICE_ACCOUNT",
)


def test_deploy_env_example_documents_pubsub_settings() -> None:
    content = DEPLOY_ENV_EXAMPLE.read_text()
    for var in PUBSUB_ENV_VARS:
        assert f"{var}=" in content
    assert "JOB_QUEUE_PROVIDER=pubsub" in content
    assert "Rollback:" in content


def test_makefile_defines_pubsub_targets() -> None:
    content = MAKEFILE.read_text()
    for target in PUBSUB_MAKE_TARGETS:
        assert f"{target}:" in content


def test_makefile_enables_pubsub_api_in_bootstrap() -> None:
    content = MAKEFILE.read_text()
    assert "pubsub.googleapis.com" in content


def test_makefile_job_queue_provider_is_configurable() -> None:
    content = MAKEFILE.read_text()
    assert "JOB_QUEUE_PROVIDER ?=" in content
    assert "MEETING_ASSISTANT_JOB_QUEUE_PROVIDER=$(JOB_QUEUE_PROVIDER)" in content
    assert "MEETING_ASSISTANT_PUBSUB_TOPIC=$(PUBSUB_TOPIC)" in content
    assert "MEETING_ASSISTANT_PUBSUB_PROJECT=$(PUBSUB_PROJECT)" in content


def test_makefile_worker_min_instances_scales_to_zero_for_pubsub() -> None:
    content = MAKEFILE.read_text()
    assert "WORKER_MIN_INSTANCES := 0" in content
    assert "WORKER_MIN_INSTANCES := 1" in content
    assert "--min-instances=$(WORKER_MIN_INSTANCES)" in content


def test_makefile_pubsub_iam_grants_publisher_and_invoker() -> None:
    content = MAKEFILE.read_text()
    assert "roles/pubsub.publisher" in content
    assert "roles/run.invoker" in content
    assert "--push-auth-service-account=" in content


def test_makefile_pubsub_disables_worker_readiness_checks() -> None:
    content = MAKEFILE.read_text()
    assert "MEETING_ASSISTANT_READINESS_CHECK_WORKER=false" in content
    assert "MEETING_ASSISTANT_READINESS_CHECK_REDIS=false" in content
