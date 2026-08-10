import json

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import ToolCall
from meeting_assistant.services.tools import ToolExecutor, build_tool_providers
from meeting_assistant.services.tools.providers.email import SendGridEmailToolProvider
from meeting_assistant.services.tools.providers.jira import JiraRestToolProvider
from meeting_assistant.services.tools.providers.slack import SlackWebhookToolProvider


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def test_calendar_tool_requires_approval() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=build_tool_providers(Settings()), sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="calendar.create_event", payload={"title": "Sync", "details": "Book it"}),
    )

    assert execution.status == "approval_required"
    assert execution.attempts == 1
    assert execution.result["approval_required"] is True

    approvals = repository.list_approval_requests(workflow_run.id)
    assert len(approvals) == 1
    assert approvals[0].tool_name == "calendar.create_event"


def test_retryable_failure_moves_to_dlq_style_failure() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(
        repository,
        providers=build_tool_providers(Settings()),
        max_retries=3,
        backoff_seconds=0,
        sleep_fn=lambda _: None,
    )

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(
            tool_name="email.send",
            payload={
                "subject": "Follow-up",
                "body": "Please send this",
                "simulate_retryable_failure": "true",
            },
        ),
    )

    assert execution.status == "failed"
    assert execution.attempts == 3
    assert execution.result["dlq"] is True


def test_duplicate_execution_reuses_existing_terminal_result() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=build_tool_providers(Settings()), sleep_fn=lambda _: None)
    tool_call = ToolCall(tool_name="email.send", payload={"subject": "Follow-up", "body": "Please send this"})

    first = executor.execute(workflow_run_id=workflow_run.id, tool_call=tool_call)
    second = executor.execute(workflow_run_id=workflow_run.id, tool_call=tool_call)

    assert first.status == "executed"
    assert second.status == "executed"
    assert second.reused is True
    assert second.idempotency_key == first.idempotency_key


def test_slack_notify_executes_via_webhook_provider() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, text="ok", headers={"X-Slack-Request-Id": "req-99"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    providers = build_tool_providers(Settings())
    providers["slack.notify"] = SlackWebhookToolProvider(
        webhook_url="https://hooks.slack.com/services/test",
        http_client=mock_client,
    )

    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Post recap to slack channel")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=providers, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(
            tool_name="slack.notify",
            payload={"channel": "#meeting-assistant", "body": "Recap: launch checklist agreed"},
        ),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "slack-webhook"
    assert execution.result["provider_message_id"] == "req-99"
    assert captured["body"]["text"] == "Recap: launch checklist agreed"


def test_email_send_executes_via_sendgrid_provider() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(202, headers={"X-Message-Id": "sg-req-99"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    providers = build_tool_providers(Settings())
    providers["email.send"] = SendGridEmailToolProvider(
        api_key="SG.test",
        from_address="noreply@example.com",
        default_recipient="team@example.com",
        http_client=mock_client,
    )

    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Send follow-up email to the team")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=providers, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(
            tool_name="email.send",
            payload={"subject": "Meeting recap", "body": "Launch checklist attached"},
        ),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "sendgrid"
    assert execution.result["provider_message_id"] == "sg-req-99"
    assert captured["body"]["subject"] == "Meeting recap"
    assert captured["body"]["personalizations"][0]["to"][0]["email"] == "team@example.com"


def test_jira_create_issue_executes_via_rest_provider() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": "10001", "key": "ENG-42"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    providers = build_tool_providers(Settings())
    providers["jira.create_issue"] = JiraRestToolProvider(
        base_url="https://example.atlassian.net",
        user_email="bot@example.com",
        api_token="token",
        project_key="ENG",
        default_issue_type="Task",
        http_client=mock_client,
    )

    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Create a jira ticket for the launch checklist")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=providers, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(
            tool_name="jira.create_issue",
            payload={
                "issue_summary": "Launch checklist follow-up",
                "issue_description": "From meeting sync",
            },
        ),
    )

    assert execution.status == "executed"
    assert execution.result["provider"] == "jira"
    assert execution.result["issue_key"] == "ENG-42"
    assert execution.result["provider_message_id"] == "10001"
    assert captured["body"]["fields"]["summary"] == "Launch checklist follow-up"


def test_jira_provider_surfaces_client_errors_as_failed_execution() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorMessages": ["Invalid project key"]})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    providers = build_tool_providers(Settings())
    providers["jira.create_issue"] = JiraRestToolProvider(
        base_url="https://example.atlassian.net",
        user_email="bot@example.com",
        api_token="token",
        project_key="ENG",
        default_issue_type="Task",
        http_client=mock_client,
    )

    repository = build_repository()
    user = repository.get_or_create_user("tool-user", "tool-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Create a jira ticket")
    workflow_run = repository.create_workflow_run(meeting.id)
    executor = ToolExecutor(repository, providers=providers, sleep_fn=lambda _: None)

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(
            tool_name="jira.create_issue",
            payload={"issue_summary": "Follow-up", "issue_description": "Details"},
        ),
    )

    assert execution.status == "failed"
    assert execution.result["dlq"] is True
    assert "Invalid project key" in execution.result["error"]
