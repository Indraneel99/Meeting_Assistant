from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

from meeting_assistant.core.config import Settings
from meeting_assistant.schemas.retrieval import (
    ChunkSearchResult,
    DecisionItem,
    MeetingSearchResult,
    QueryCitation,
)

logger = logging.getLogger("uvicorn.error")


@dataclass(slots=True)
class RetrievalContext:
    question: str
    meetings: list[MeetingSearchResult]
    chunks: list[ChunkSearchResult]
    decisions: list[DecisionItem]


class QueryAnswerer(Protocol):
    def answer(self, context: RetrievalContext) -> tuple[str, list[QueryCitation]]:
        ...


@dataclass(slots=True)
class HeuristicQueryAnswerer:
    def answer(self, context: RetrievalContext) -> tuple[str, list[QueryCitation]]:
        if not context.meetings and not context.chunks and not context.decisions:
            return "No matching meeting history was found for that question yet.", []

        citations: list[QueryCitation] = []
        parts: list[str] = [f"Answer for: {context.question}"]

        for meeting in context.meetings[:2]:
            excerpt = meeting.summary[:240]
            citations.append(
                QueryCitation(
                    meeting_id=meeting.meeting_id,
                    meeting_title=meeting.title,
                    source_type="meeting",
                    excerpt=excerpt,
                )
            )
            parts.append(f"[{meeting.title}] {meeting.summary}")

        for chunk in context.chunks[:3]:
            excerpt = chunk.text[:240]
            citations.append(
                QueryCitation(
                    meeting_id=chunk.meeting_id,
                    meeting_title=chunk.meeting_title,
                    source_type="chunk",
                    excerpt=excerpt,
                )
            )
            parts.append(f"[{chunk.meeting_title} excerpt] {chunk.text}")

        for decision in context.decisions[:3]:
            excerpt = decision.decision_text[:240]
            citations.append(
                QueryCitation(
                    meeting_id=decision.meeting_id,
                    meeting_title=decision.topic,
                    source_type="decision",
                    excerpt=excerpt,
                )
            )
            parts.append(f"[Decision: {decision.topic}] {decision.decision_text}")

        return " ".join(parts), citations


@dataclass(slots=True)
class OpenAIQueryAnswerer:
    model_name: str
    client: OpenAI

    def answer(self, context: RetrievalContext) -> tuple[str, list[QueryCitation]]:
        if not context.meetings and not context.chunks and not context.decisions:
            return "No matching meeting history was found for that question yet.", []

        context_blocks: list[str] = []
        citations: list[QueryCitation] = []

        for meeting in context.meetings:
            excerpt = meeting.summary[:500]
            context_blocks.append(f"Meeting: {meeting.title}\nSummary: {excerpt}")
            citations.append(
                QueryCitation(
                    meeting_id=meeting.meeting_id,
                    meeting_title=meeting.title,
                    source_type="meeting",
                    excerpt=excerpt,
                )
            )

        for chunk in context.chunks:
            excerpt = chunk.text[:500]
            context_blocks.append(f"Meeting: {chunk.meeting_title}\nTranscript excerpt: {excerpt}")
            citations.append(
                QueryCitation(
                    meeting_id=chunk.meeting_id,
                    meeting_title=chunk.meeting_title,
                    source_type="chunk",
                    excerpt=excerpt,
                )
            )

        for decision in context.decisions:
            excerpt = decision.decision_text[:500]
            context_blocks.append(f"Decision topic: {decision.topic}\nDecision: {excerpt}")
            citations.append(
                QueryCitation(
                    meeting_id=decision.meeting_id,
                    meeting_title=decision.topic,
                    source_type="decision",
                    excerpt=excerpt,
                )
            )

        prompt = (
            "You are a meeting assistant. Answer the user's question using only the retrieved context. "
            "Cite meeting titles inline when referencing specific evidence. "
            "If the context is insufficient, say what is missing.\n\n"
            f"Question: {context.question}\n\n"
            "Retrieved context:\n"
            + "\n\n".join(context_blocks)
        )

        logger.info("Query answerer provider=openai model=%s", self.model_name)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": "Provide concise, factual answers with meeting citations."},
                {"role": "user", "content": prompt},
            ],
        )
        answer = response.choices[0].message.content or "Unable to generate an answer from the retrieved context."
        return answer.strip(), citations


def build_query_answerer(settings: Settings, llm_client: OpenAI | None = None) -> QueryAnswerer:
    if settings.query_provider == "openai" and settings.llm_openai_api_key:
        client = llm_client or OpenAI(
            api_key=settings.llm_openai_api_key,
            base_url=settings.llm_openai_base_url,
            timeout=settings.llm_openai_timeout_seconds,
        )
        return OpenAIQueryAnswerer(model_name=settings.query_openai_model, client=client)
    return HeuristicQueryAnswerer()
