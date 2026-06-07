from dataclasses import dataclass, field

from meeting_assistant.schemas.planner import PlanResult
from meeting_assistant.services.context import ContextBundle
from meeting_assistant.services.planner import HeuristicPlanner, OpenAIPlanner, PlannerRouter, PlannerRuntimeState


@dataclass
class FakeParsedResponse:
    output_parsed: PlanResult | None


@dataclass
class FakeResponsesClient:
    response: FakeParsedResponse | None = None
    error: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[PlanResult],
    ) -> FakeParsedResponse:
        self.calls.append({"model": model, "input": input, "text_format": text_format})
        if self.error:
            raise self.error
        if self.response is None:
            raise ValueError("Missing fake response.")
        return self.response


@dataclass
class FakeOpenAIClient:
    responses: FakeResponsesClient


def test_heuristic_planner_extracts_basic_structure() -> None:
    planner = HeuristicPlanner()

    result = planner.plan(
        "Weekly sync",
        "Decision: ship Friday. Action: send recap. Schedule a calendar check-in.",
        ContextBundle(recent_summaries=[], relevant_summaries=[]),
        PlannerRuntimeState(iteration=1, max_iterations=3),
    )

    assert result.summary
    assert result.tasks
    assert result.decisions
    assert any(call.tool_name == "calendar.create_event" for call in result.tool_calls)


def test_openai_planner_parses_structured_output() -> None:
    structured_plan = PlanResult(
        summary="Weekly sync finalized the Friday launch plan.",
        tasks=[{"assignee": "Ava", "action": "Send the recap email"}],
        decisions=[{"topic": "Launch", "decision_text": "Ship on Friday"}],
        tool_calls=[{"tool_name": "email.send", "payload": {"subject": "Recap", "body": "Send recap"}}],
    )

    responses = FakeResponsesClient(response=FakeParsedResponse(output_parsed=structured_plan))

    planner = OpenAIPlanner(
        model_name="gpt-5.4-mini",
        client=FakeOpenAIClient(responses=responses),
    )

    result = planner.plan(
        "Weekly sync",
        "Decision: ship Friday. Action: send recap.",
        ContextBundle(recent_summaries=["Previous launch slipped."], relevant_summaries=[]),
        PlannerRuntimeState(iteration=1, max_iterations=3),
    )

    assert result == structured_plan
    assert responses.calls[0]["model"] == "gpt-5.4-mini"
    assert responses.calls[0]["text_format"] is PlanResult


def test_planner_router_falls_back_when_primary_fails() -> None:
    router = PlannerRouter(
        primary=OpenAIPlanner(
            model_name="gpt-5.4-mini",
            client=FakeOpenAIClient(responses=FakeResponsesClient(error=RuntimeError("boom"))),
        ),
        fallback=HeuristicPlanner(),
    )

    result = router.plan(
        "Weekly sync",
        "Action: send recap. Decision: keep the Friday launch.",
        ContextBundle(recent_summaries=[], relevant_summaries=[]),
        PlannerRuntimeState(iteration=1, max_iterations=3),
    )

    assert result.summary
    assert result.tasks
