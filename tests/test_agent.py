from dataclasses import dataclass

from meeting_assistant.db.models import Base
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.planner import PlanResult
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.context import ContextBundle
from meeting_assistant.services.planner import Planner, PlannerRuntimeState
from meeting_assistant.services.tools import ToolExecutor, ToolValidator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_repository() -> Repository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return Repository(session_local)


def build_workflow_run(repository: Repository) -> int:
    user = repository.get_or_create_user("agent-user", "agent-user@example.com")
    meeting = repository.create_meeting(user.id, "Weekly sync", None, "Transcript")
    workflow_run = repository.create_workflow_run(meeting.id)
    return workflow_run.id


@dataclass
class StubPlanner(Planner):
    plans: list[PlanResult]

    def plan(
        self,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        runtime_state: PlannerRuntimeState | None = None,
    ) -> PlanResult:
        index = min((runtime_state.iteration - 1 if runtime_state else 0), len(self.plans) - 1)
        return self.plans[index]


def test_agent_runtime_stops_when_no_more_tool_calls() -> None:
    repository = build_repository()
    runtime = AgentRuntime(
        repository=repository,
        planner=StubPlanner(
            plans=[
                PlanResult(
                    summary="Sent follow-up.",
                    tasks=[{"assignee": "Ava", "action": "Send follow-up"}],
                    decisions=[],
                    tool_calls=[{"tool_name": "email.send", "payload": {"subject": "s", "body": "b"}}],
                ),
                PlanResult(
                    summary="Follow-up completed.",
                    tasks=[{"assignee": "Ava", "action": "Send follow-up"}],
                    decisions=[],
                    tool_calls=[],
                ),
            ]
        ),
        tool_validator=ToolValidator(),
        tool_executor=ToolExecutor(repository, sleep_fn=lambda _: None),
        max_iterations=4,
    )
    workflow_run_id = build_workflow_run(repository)

    result = runtime.run(
        workflow_run_id=workflow_run_id,
        title="Weekly sync",
        transcript_text="Please send a follow-up email.",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert result.status == "done"
    assert result.iterations_used == 2
    assert result.tool_executions[0]["status"] == "executed"


def test_agent_runtime_pauses_on_approval() -> None:
    repository = build_repository()
    runtime = AgentRuntime(
        repository=repository,
        planner=StubPlanner(
            plans=[
                PlanResult(
                    summary="Need calendar booking.",
                    tasks=[],
                    decisions=[],
                    tool_calls=[{"tool_name": "calendar.create_event", "payload": {"title": "Sync", "details": "Book"}}],
                )
            ]
        ),
        tool_validator=ToolValidator(),
        tool_executor=ToolExecutor(repository, sleep_fn=lambda _: None),
        max_iterations=4,
    )
    workflow_run_id = build_workflow_run(repository)

    result = runtime.run(
        workflow_run_id=workflow_run_id,
        title="Weekly sync",
        transcript_text="Schedule the next meeting.",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert result.status == "awaiting_approval"
    assert result.tool_executions[0]["status"] == "approval_required"


def test_agent_runtime_resume_after_approval() -> None:
    repository = build_repository()
    runtime = AgentRuntime(
        repository=repository,
        planner=StubPlanner(
            plans=[
                PlanResult(
                    summary="Need calendar booking.",
                    tasks=[],
                    decisions=[],
                    tool_calls=[{"tool_name": "calendar.create_event", "payload": {"title": "Sync", "details": "Book"}}],
                ),
                PlanResult(
                    summary="Calendar handled.",
                    tasks=[],
                    decisions=[],
                    tool_calls=[],
                ),
            ]
        ),
        tool_validator=ToolValidator(),
        tool_executor=ToolExecutor(repository, sleep_fn=lambda _: None),
        max_iterations=4,
    )
    workflow_run_id = build_workflow_run(repository)

    paused = runtime.run(
        workflow_run_id=workflow_run_id,
        title="Weekly sync",
        transcript_text="Schedule the next meeting.",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )
    assert paused.status == "awaiting_approval"

    approval = repository.list_approval_requests(workflow_run_id)[0]
    ToolExecutor(repository, sleep_fn=lambda _: None).finalize_approval(approval.tool_execution_id, approved=True)
    repository.update_agent_step_for_tool(workflow_run_id, approval.tool_name, "executed")

    resumed = runtime.resume(
        workflow_run_id=workflow_run_id,
        title="Weekly sync",
        transcript_text="Schedule the next meeting.",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert resumed.status == "done"
    assert any(item["status"] == "executed" for item in resumed.tool_executions)


def test_agent_runtime_loop_guard_stops_repeated_calls() -> None:
    repository = build_repository()
    repeated_plan = PlanResult(
        summary="Trying the same thing again.",
        tasks=[],
        decisions=[],
        tool_calls=[{"tool_name": "email.send", "payload": {"subject": "same", "body": "same"}}],
    )
    runtime = AgentRuntime(
        repository=repository,
        planner=StubPlanner(plans=[repeated_plan, repeated_plan, repeated_plan]),
        tool_validator=ToolValidator(),
        tool_executor=ToolExecutor(repository, sleep_fn=lambda _: None),
        max_iterations=4,
    )
    workflow_run_id = build_workflow_run(repository)

    result = runtime.run(
        workflow_run_id=workflow_run_id,
        title="Weekly sync",
        transcript_text="Please send the same recap.",
        context=ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert result.status == "done"
    assert result.iterations_used == 2
    assert len(result.tool_executions) == 1
