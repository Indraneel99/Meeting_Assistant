from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from meeting_assistant.core.config import Settings
from meeting_assistant.db.models import Base, IntegrationProvider
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import PlanResult, ToolCall
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.context import ContextBundle
from meeting_assistant.services.planner import HeuristicPlanner, PlannerRuntimeState, filter_tool_calls_by_availability
from meeting_assistant.services.token_encryption import TokenEncryptor
from meeting_assistant.services.tools import ToolExecutor, ToolValidator, build_tool_providers
from meeting_assistant.services.tools.user_factory import UserToolProviderFactory


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def build_factory(
    repository: Repository,
    *,
    settings: Settings | None = None,
    encryptor: TokenEncryptor | None = None,
) -> UserToolProviderFactory:
    import httpx

    resolved_encryptor = encryptor or TokenEncryptor(Fernet.generate_key().decode())
    return UserToolProviderFactory(
        repository,
        encryptor=resolved_encryptor,
        settings=settings or Settings(),
        http_client=httpx.Client(),
    )


def test_available_tools_includes_only_connected_tools_when_user_has_integrations() -> None:
    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("tools-user", "tools-user@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.SLACK,
        provider_account_id="T123",
        access_token="xoxb-test",
        settings_json={"channels": ["#general"]},
    )
    factory = build_factory(repository, encryptor=encryptor)

    tools = factory.available_tools(user.id)

    assert tools == frozenset({"slack.notify"})


def test_available_tools_without_user_integrations_uses_deploy_stub_fallback() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tools-user", "tools-user@example.com")
    factory = build_factory(repository)

    tools = factory.available_tools(user.id)

    assert tools == frozenset({"slack.notify", "email.send", "calendar.create_event"})


def test_filter_tool_calls_by_availability() -> None:
    tool_calls = [
        ToolCall(tool_name="email.send", payload={"subject": "Hi", "body": "Body"}),
        ToolCall(tool_name="slack.notify", payload={"body": "Ping"}),
    ]

    filtered = filter_tool_calls_by_availability(tool_calls, frozenset({"email.send"}))

    assert len(filtered) == 1
    assert filtered[0].tool_name == "email.send"


def test_heuristic_planner_filters_unavailable_tools() -> None:
    planner = HeuristicPlanner()
    runtime_state = PlannerRuntimeState(
        iteration=1,
        max_iterations=3,
        available_tools=frozenset({"email.send"}),
    )

    result = planner.plan(
        "Weekly sync",
        "Please email the team and post to slack and schedule a calendar follow-up.",
        ContextBundle(recent_summaries=[], relevant_summaries=[]),
        runtime_state,
    )

    assert {call.tool_name for call in result.tool_calls} == {"email.send"}


def test_tool_executor_returns_integration_not_connected_without_providers() -> None:
    repository = build_repository()
    user = repository.get_or_create_user("tools-user", "tools-user@example.com")
    meeting = repository.create_meeting(user.id, "Sync", None, "Please email the team.")
    workflow_run = repository.create_workflow_run(meeting.id)
    factory = build_factory(repository)
    executor = ToolExecutor(
        repository,
        providers={},
        user_tool_factory=factory,
        sleep_fn=lambda _: None,
    )

    execution = executor.execute(
        workflow_run_id=workflow_run.id,
        tool_call=ToolCall(tool_name="email.send", payload={"subject": "Recap", "body": "Summary"}),
    )

    assert execution.status == "skipped"
    assert execution.result["error"] == "integration_not_connected"
    assert execution.result["tool_name"] == "email.send"


def test_agent_runtime_passes_available_tools_to_planner() -> None:
    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("agent-user", "agent-user@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.EMAIL_PREFS,
        provider_account_id="email-prefs",
        access_token="",
        settings_json={"notifications_enabled": True, "notification_emails": ["agent-user@example.com"]},
    )
    meeting = repository.create_meeting(
        user.id,
        "Weekly sync",
        None,
        "Please email the team and post to slack.",
    )
    workflow_run = repository.create_workflow_run(meeting.id)
    factory = build_factory(repository, encryptor=encryptor)
    executor = ToolExecutor(
        repository,
        providers=build_tool_providers(Settings()),
        user_tool_factory=factory,
        sleep_fn=lambda _: None,
    )
    runtime = AgentRuntime(
        repository=repository,
        planner=HeuristicPlanner(),
        tool_validator=ToolValidator(),
        tool_executor=executor,
        max_iterations=2,
        user_tool_factory=factory,
    )

    result = runtime.run(
        workflow_run_id=workflow_run.id,
        title="Weekly sync",
        transcript_text="Please email the team and post to slack.",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert result.status == "done"
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0]["tool_name"] == "email.send"
    assert result.tool_executions[0]["status"] == "executed"


def test_stub_planner_filters_tool_calls_when_available_tools_restricted() -> None:
    class RecordingPlanner:
        def plan(self, title, transcript_text, context, runtime_state=None):
            assert runtime_state is not None
            assert runtime_state.available_tools == frozenset({"email.send"})
            return PlanResult(
                summary="Summary",
                tasks=[],
                decisions=[],
                tool_calls=[
                    ToolCall(tool_name="email.send", payload={"subject": "s", "body": "b"}),
                    ToolCall(tool_name="slack.notify", payload={"body": "b"}),
                ],
            )

    repository = build_repository()
    encryptor = TokenEncryptor(Fernet.generate_key().decode())
    user = repository.get_or_create_user("agent-user", "agent-user@example.com")
    repository.upsert_user_integration(
        encryptor=encryptor,
        user_id=user.id,
        provider=IntegrationProvider.EMAIL_PREFS,
        provider_account_id="email-prefs",
        access_token="",
        settings_json={"notifications_enabled": True, "notification_emails": ["agent-user@example.com"]},
    )
    meeting = repository.create_meeting(user.id, "Sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    factory = build_factory(repository, encryptor=encryptor)
    runtime = AgentRuntime(
        repository=repository,
        planner=RecordingPlanner(),
        tool_validator=ToolValidator(),
        tool_executor=ToolExecutor(
            repository,
            providers=build_tool_providers(Settings()),
            user_tool_factory=factory,
            sleep_fn=lambda _: None,
        ),
        max_iterations=1,
        user_tool_factory=factory,
    )

    result = runtime.run(
        workflow_run_id=workflow_run.id,
        title="Sync",
        transcript_text="Transcript",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert len(result.tool_executions) == 1
    assert result.tool_executions[0]["tool_name"] == "email.send"
