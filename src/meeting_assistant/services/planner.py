from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from meeting_assistant.schemas.planner import PlanResult, PlannedDecision, PlannedTask, ToolCall
from meeting_assistant.services.context import ContextBundle


class Planner(Protocol):
    def plan(self, title: str, transcript_text: str, context: ContextBundle) -> PlanResult:
        ...


class HeuristicPlanner:
    """Development planner that mimics a structured LLM response.

    Replace this with a model adapter around vLLM/Qwen guided decoding in production.
    """

    def plan(self, title: str, transcript_text: str, context: ContextBundle) -> PlanResult:
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


def build_planner_messages(title: str, transcript_text: str, context: ContextBundle) -> list[dict[str, str]]:
    recent_summaries = "\n".join(f"- {item}" for item in context.recent_summaries) or "- None"
    relevant_summaries = "\n".join(f"- {item}" for item in context.relevant_summaries) or "- None"

    system_prompt = (
        "You are a meeting assistant planner. "
        "Extract a concise summary, action items, decisions, and optional tool calls. "
        "Return data that exactly matches the provided JSON schema."
    )
    user_prompt = (
        f"Meeting title: {title}\n\n"
        f"Recent meeting summaries:\n{recent_summaries}\n\n"
        f"Semantically relevant summaries:\n{relevant_summaries}\n\n"
        f"Transcript:\n{transcript_text}\n\n"
        "Guidance:\n"
        "- Keep the summary short and factual.\n"
        "- Extract concrete tasks with assignee when present, otherwise use 'unassigned'.\n"
        "- Extract important decisions with a clear topic.\n"
        "- Only create tool calls when the meeting explicitly asks for an email or a calendar action.\n"
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

    def plan(self, title: str, transcript_text: str, context: ContextBundle) -> PlanResult:
        response = self.http_client.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "messages": build_planner_messages(title, transcript_text, context),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "meeting_plan",
                        "strict": True,
                        "schema": PlanResult.model_json_schema(),
                    },
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            content_text = "".join(text_parts).strip()
        else:
            content_text = str(content).strip()

        return PlanResult.model_validate(json.loads(content_text))


@dataclass(slots=True)
class PlannerRouter:
    primary: Planner
    fallback: Planner | None = None

    def plan(self, title: str, transcript_text: str, context: ContextBundle) -> PlanResult:
        try:
            return self.primary.plan(title, transcript_text, context)
        except Exception:
            if self.fallback is None:
                raise
            return self.fallback.plan(title, transcript_text, context)
