import json

import httpx

from meeting_assistant.schemas.planner import PlanResult
from meeting_assistant.services.context import ContextBundle
from meeting_assistant.services.planner import HeuristicPlanner, OpenAIPlanner, PlannerRouter


def test_heuristic_planner_extracts_basic_structure() -> None:
    planner = HeuristicPlanner()

    result = planner.plan(
        "Weekly sync",
        "Decision: ship Friday. Action: send recap. Schedule a calendar check-in.",
        ContextBundle(recent_summaries=[], relevant_summaries=[]),
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

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "gpt-5.4-mini"
        assert payload["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": structured_plan.model_dump_json(),
                        }
                    }
                ]
            },
        )

    planner = OpenAIPlanner(
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model_name="gpt-5.4-mini",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = planner.plan(
        "Weekly sync",
        "Decision: ship Friday. Action: send recap.",
        ContextBundle(recent_summaries=["Previous launch slipped."], relevant_summaries=[]),
    )

    assert result == structured_plan


def test_planner_router_falls_back_when_primary_fails() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    router = PlannerRouter(
        primary=OpenAIPlanner(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model_name="gpt-5.4-mini",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
        fallback=HeuristicPlanner(),
    )

    result = router.plan(
        "Weekly sync",
        "Action: send recap. Decision: keep the Friday launch.",
        ContextBundle(recent_summaries=[], relevant_summaries=[]),
    )

    assert result.summary
    assert result.tasks
