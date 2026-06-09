from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from openai import APIStatusError

from meeting_assistant.schemas.planner import PlannedDecision, PlannedTask, PlanResult, ToolCall
from meeting_assistant.services.context import ContextBundle

# Use uvicorn's app logger so planner logs are visible in dev server output.
logger = logging.getLogger("uvicorn.error")


@dataclass(slots=True)
class PlannerHistoryEntry:
    iteration: int
    step_kind: str
    status: str
    detail: str


@dataclass(slots=True)
class PlannerRuntimeState:
    iteration: int
    max_iterations: int
    history: list[PlannerHistoryEntry] = field(default_factory=list)


class Planner(Protocol):
    def plan(
        self,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        runtime_state: PlannerRuntimeState | None = None,
    ) -> PlanResult:
        ...


class OpenAIParsedResponse(Protocol):
    output_parsed: PlanResult | None


class OpenAIResponsesClient(Protocol):
    def parse(
        self,
        *,
        model: str,
        input: list[dict[str, str]],
        text_format: type[PlanResult],
    ) -> OpenAIParsedResponse:
        ...


class OpenAIClient(Protocol):
    responses: OpenAIResponsesClient


class HeuristicPlanner:
    """Development planner that mimics a structured LLM response.

    Replace this with a model adapter around vLLM/Qwen guided decoding in production.
    """

    def plan(
        self,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        runtime_state: PlannerRuntimeState | None = None,
    ) -> PlanResult:
        logger.info(
            "Planner provider=heuristic mode=direct_parse iteration=%s",
            runtime_state.iteration if runtime_state else 1,
        )
        sentences = [sentence.strip() for sentence in transcript_text.replace("\n", " ").split(".") if sentence.strip()]
        summary_seed = " ".join(sentences[:3]).strip() or transcript_text[:240]
        context_note = ""
        if context.relevant_summaries:
            context_note = f" Related past work: {context.relevant_summaries[0]}"
        summary = f"{title}: {summary_seed}.{context_note}".strip()

        tasks: list[PlannedTask] = []
        decisions: list[PlannedDecision] = []
        tool_calls: list[ToolCall] = []

        for sentence in sentences:
            lowered = sentence.lower()
            if "action:" in lowered or "todo:" in lowered:
                _, action_text = sentence.split(":", 1)
                tasks.append(PlannedTask(assignee="unassigned", action=action_text.strip()))
            if lowered.startswith("decision:") or " decided " in lowered:
                decision_text = sentence.split(":", 1)[1].strip() if ":" in sentence else sentence
                decisions.append(PlannedDecision(topic=title, decision_text=decision_text))
            if "email" in lowered:
                tool_calls.append(
                    ToolCall(
                        tool_name="email.send",
                        payload={"subject": f"Follow-up for {title}", "body": sentence},
                    )
                )
            if "calendar" in lowered or "schedule" in lowered:
                tool_calls.append(
                    ToolCall(
                        tool_name="calendar.create_event",
                        payload={"title": title, "details": sentence},
                    )
                )
            if "slack" in lowered:
                tool_calls.append(
                    ToolCall(
                        tool_name="slack.notify",
                        payload={"channel": "general", "body": sentence},
                    )
                )
            if "jira" in lowered or "ticket" in lowered:
                tool_calls.append(
                    ToolCall(
                        tool_name="jira.create_issue",
                        payload={"issue_summary": sentence, "issue_description": sentence},
                    )
                )

        if not tasks and sentences:
            tasks.append(PlannedTask(assignee="unassigned", action=f"Review outcomes from {title}"))

        return PlanResult(summary=summary, tasks=tasks[:10], decisions=decisions[:10], tool_calls=tool_calls[:10])


def build_planner_messages(
    title: str,
    transcript_text: str,
    context: ContextBundle,
    runtime_state: PlannerRuntimeState | None = None,
) -> list[dict[str, str]]:
    recent_summaries = "\n".join(f"- {item}" for item in context.recent_summaries) or "- None"
    relevant_summaries = "\n".join(f"- {item}" for item in context.relevant_summaries) or "- None"
    history_block = "- None"
    if runtime_state and runtime_state.history:
        history_block = "\n".join(
            f"- Iteration {item.iteration} [{item.step_kind}/{item.status}]: {item.detail}"
            for item in runtime_state.history
        )

    system_prompt = (
        "You are a meeting assistant planner. "
        "Extract a concise summary, action items, decisions, and next tool calls. "
        "Return data that exactly matches the provided JSON schema."
    )
    user_prompt = (
        f"Meeting title: {title}\n\n"
        f"Iteration: {(runtime_state.iteration if runtime_state else 1)} of "
        f"{(runtime_state.max_iterations if runtime_state else 1)}\n\n"
        f"Recent meeting summaries:\n{recent_summaries}\n\n"
        f"Semantically relevant summaries:\n{relevant_summaries}\n\n"
        f"Execution history:\n{history_block}\n\n"
        f"Transcript:\n{transcript_text}\n\n"
        "Guidance:\n"
        "- Keep the summary short and factual.\n"
        "- Extract concrete tasks with assignee when present, otherwise use 'unassigned'.\n"
        "- Extract important decisions with a clear topic.\n"
        "- Only create tool calls when the meeting explicitly asks for an email, calendar, Slack, or Jira action.\n"
        "- Do not repeat a tool call that already succeeded or is awaiting approval in the execution history.\n"
        "- If previous tool results already satisfy the request, return no tool calls.\n"
        "- Use tool names email.send, calendar.create_event, slack.notify, and jira.create_issue.\n"
        "- Tool payloads must include subject, body, title, details, target, recipient, channel, "
        "issue_summary, issue_description, issue_type, and simulate_retryable_failure. "
        "Use empty strings for irrelevant payload fields.\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


@dataclass(slots=True)
class OpenAIPlanner:
    model_name: str
    client: OpenAIClient

    def plan(
        self,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        runtime_state: PlannerRuntimeState | None = None,
    ) -> PlanResult:
        logger.info(
            "Planner provider=openai sdk=responses.parse model=%s iteration=%s",
            self.model_name,
            runtime_state.iteration if runtime_state else 1,
        )
        response = self.client.responses.parse(
            model=self.model_name,
            input=build_planner_messages(title, transcript_text, context, runtime_state),
            text_format=PlanResult,
        )
        if response.output_parsed is None:
            raise ValueError("OpenAI planner returned no parsed output.")
        return response.output_parsed


@dataclass(slots=True)
class PlannerRouter:
    primary: Planner
    fallback: Planner | None = None

    def plan(
        self,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        runtime_state: PlannerRuntimeState | None = None,
    ) -> PlanResult:
        try:
            return self.primary.plan(title, transcript_text, context, runtime_state)
        except Exception as exc:
            if self.fallback is None:
                raise
            if isinstance(exc, APIStatusError):
                logger.error(
                    "Primary planner OpenAI API error status=%s body=%s",
                    exc.status_code,
                    exc.response.text,
                )
            elif isinstance(exc, httpx.HTTPStatusError):
                status_code = exc.response.status_code
                response_body = exc.response.text
                logger.error(
                    "Primary planner HTTP error status=%s body=%s",
                    status_code,
                    response_body,
                )
            else:
                logger.error("Primary planner error details: %s", str(exc), exc_info=True)
            logger.warning(
                "Primary planner failed (%s); falling back to %s",
                exc.__class__.__name__,
                self.fallback.__class__.__name__,
            )
            return self.fallback.plan(title, transcript_text, context, runtime_state)
