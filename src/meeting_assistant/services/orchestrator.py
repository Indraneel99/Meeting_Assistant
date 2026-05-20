from __future__ import annotations

import json
from dataclasses import dataclass

from meeting_assistant.db.models import WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.batch import BatchMeetingRequest
from meeting_assistant.services.asr import BatchASRAdapter
from meeting_assistant.services.context import ContextLoader
from meeting_assistant.services.embeddings import InMemoryEmbeddingIndex
from meeting_assistant.services.normalizer import TranscriptNormalizer
from meeting_assistant.services.planner import Planner
from meeting_assistant.services.queue import InMemoryTranscriptQueue
from meeting_assistant.services.tools import ToolExecutor, ToolValidator


@dataclass(slots=True)
class BatchOrchestrator:
    repository: Repository
    queue: InMemoryTranscriptQueue
    asr: BatchASRAdapter
    normalizer: TranscriptNormalizer
    planner: Planner
    context_loader: ContextLoader
    embedding_index: InMemoryEmbeddingIndex
    tool_validator: ToolValidator
    tool_executor: ToolExecutor

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

            plan = self.planner.plan(payload.title, assembled_transcript, context)
            validated_tool_calls = self.tool_validator.validate(plan.tool_calls)

            executed_count = 0
            tool_execution_records: list[dict[str, object]] = []
            for tool_call in validated_tool_calls:
                result = self.tool_executor.execute(workflow_run.id, tool_call)
                executed_count += 1 if result.status in {"executed", "approval_required"} else 0
                tool_execution_records.append(
                    {
                        "tool_name": tool_call.tool_name,
                        "status": result.status,
                        "attempts": result.attempts,
                        "idempotency_key": result.idempotency_key,
                        "result": result.result,
                    }
                )

            embedding = self.embedding_index.embed(plan.summary)
            self.repository.complete_meeting(
                meeting_id=meeting.id,
                summary_text=plan.summary,
                summary_embedding=embedding,
                tasks=[task.model_dump() for task in plan.tasks],
                decisions=[decision.model_dump() for decision in plan.decisions],
            )
            self.repository.update_workflow_status(workflow_run.id, WorkflowStatus.DONE)
        except Exception as exc:
            self.repository.update_workflow_status(workflow_run.id, WorkflowStatus.FAILED, str(exc))
            raise

        return {
            "meeting_id": meeting.id,
            "workflow_run_id": workflow_run.id,
            "status": WorkflowStatus.DONE.value,
            "summary": plan.summary,
            "tasks_created": len(plan.tasks),
            "decisions_logged": len(plan.decisions),
            "tool_calls_recorded": executed_count,
            "tool_executions": tool_execution_records,
        }
