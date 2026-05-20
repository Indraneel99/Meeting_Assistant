from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from meeting_assistant.schemas.planner import PlanResult, PlannedDecision, PlannedTask, ToolCall
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
        "- Only create tool calls when the meeting explicitly asks for an email or a calendar action.\n"
        "- Do not repeat a tool call that already succeeded or is awaiting approval in the execution history.\n"
        "- If previous tool results already satisfy the request, return no tool calls.\n"
        "- Use tool names email.send and calendar.create_event.\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


@dataclass(slots=True)
class OpenAIPlanner:
    api_key: str
    base_url: str
    model_name: str
    http_client: httpx.Client

    def plan(
        self,
        title: str,
        transcript_text: str,
        context: ContextBundle,
        runtime_state: PlannerRuntimeState | None = None,
    ) -> PlanResult:
        schema = PlanResult.model_json_schema()
        logger.info(
            "Planner provider=openai api=responses model=%s iteration=%s",
            self.model_name,
            runtime_state.iteration if runtime_state else 1,
        )
        response = self.http_client.post(
            f"{self.base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "input": build_planner_messages(title, transcript_text, context, runtime_state),
                "text_format": PlanResult,
            },
        )
        response.raise_for_status()
        payload = response.json()

        text_parts: list[str] = []
        for output_item in payload.get("output", []):
            if output_item.get("type") != "message":
                continue
            for content_item in output_item.get("content", []):
                if content_item.get("type") == "output_text":
                    text_parts.append(content_item.get("text", ""))

        content_text = "".join(text_parts).strip()

        return PlanResult.model_validate(json.loads(content_text))


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
            if isinstance(exc, httpx.HTTPStatusError):
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
