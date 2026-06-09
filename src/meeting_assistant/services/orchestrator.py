from __future__ import annotations

import json
from dataclasses import dataclass

from meeting_assistant.db.models import WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.batch import BatchMeetingRequest
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.asr import BatchASRAdapter
from meeting_assistant.services.context import ContextLoader
from meeting_assistant.services.embeddings import EmbeddingIndex
from meeting_assistant.services.normalizer import TranscriptNormalizer
from meeting_assistant.services.queue import InMemoryTranscriptQueue


@dataclass(slots=True)
class BatchOrchestrator:
    repository: Repository
    queue: InMemoryTranscriptQueue
    asr: BatchASRAdapter
    normalizer: TranscriptNormalizer
    context_loader: ContextLoader
    embedding_index: EmbeddingIndex
    agent_runtime: AgentRuntime

    def process_batch_meeting(self, payload: BatchMeetingRequest) -> dict[str, object]:
        user = self.repository.get_or_create_user(payload.user_external_id, payload.user_email)
        transcript = self.asr.transcribe(payload.source_uri, payload.transcript_text)
        transcript_text = transcript.rendered_text()
        meeting = self.repository.create_meeting(user.id, payload.title, payload.source_uri, transcript_text)
        workflow_run = self.repository.create_workflow_run(meeting.id)

        try:
            self.repository.save_transcript_artifact(meeting.id, transcript)
            normalized = self.normalizer.normalize(transcript_text)
            chunks = self.normalizer.chunk(normalized)
            self.repository.replace_chunks(meeting.id, chunks)
            self.queue.publish(meeting.id, chunks)
            self.repository.update_workflow_status(workflow_run.id, WorkflowStatus.VALIDATED)

            assembled_transcript = " ".join(self.queue.drain(meeting.id))
            context = self.context_loader.load(user.id, assembled_transcript)
            self.repository.update_workflow_status(workflow_run.id, WorkflowStatus.EXECUTING)

            agent_result = self.agent_runtime.run(
                workflow_run_id=workflow_run.id,
                title=payload.title,
                transcript_text=assembled_transcript,
                context=context,
            )

            embedding = self.embedding_index.embed(agent_result.summary)
            self.repository.complete_meeting(
                meeting_id=meeting.id,
                summary_text=agent_result.summary,
                summary_embedding=embedding,
                tasks=[task.model_dump() for task in agent_result.tasks],
                decisions=[decision.model_dump() for decision in agent_result.decisions],
            )
            self.repository.update_workflow_status(workflow_run.id, WorkflowStatus(agent_result.status))
        except Exception as exc:
            self.repository.update_workflow_status(workflow_run.id, WorkflowStatus.FAILED, str(exc))
            raise

        return {
            "meeting_id": meeting.id,
            "workflow_run_id": workflow_run.id,
            "status": agent_result.status,
            "summary": agent_result.summary,
            "tasks_created": len(agent_result.tasks),
            "decisions_logged": len(agent_result.decisions),
            "tool_calls_recorded": sum(
                1 for item in agent_result.tool_executions if item["status"] in {"executed", "approval_required"}
            ),
            "iterations_used": agent_result.iterations_used,
            "tool_executions": agent_result.tool_executions,
        }
