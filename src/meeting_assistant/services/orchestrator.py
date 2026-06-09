from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from meeting_assistant.db.models import WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.batch import BatchMeetingRequest, BatchMeetingResponse
from meeting_assistant.schemas.workflow import WorkflowStatusResponse, WorkflowToolExecutionRecord
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.asr import BatchASRAdapter
from meeting_assistant.services.context import ContextLoader
from meeting_assistant.services.embeddings import EmbeddingIndex
from meeting_assistant.services.jobs import BatchJobQueue
from meeting_assistant.services.normalizer import TranscriptNormalizer
from meeting_assistant.services.queue import TranscriptQueue


@dataclass(slots=True)
class BatchOrchestrator:
    repository: Repository
    queue: TranscriptQueue
    asr: BatchASRAdapter
    normalizer: TranscriptNormalizer
    context_loader: ContextLoader
    embedding_index: EmbeddingIndex
    agent_runtime: AgentRuntime
    job_queue: BatchJobQueue
    batch_processing_mode: str = "sync"

    def submit_batch_meeting(self, payload: BatchMeetingRequest) -> dict[str, object]:
        if self.batch_processing_mode == "async":
            user = self.repository.get_or_create_user(payload.user_external_id, payload.user_email)
            meeting = self.repository.create_meeting(user.id, payload.title, payload.source_uri, "")
            workflow_run = self.repository.create_workflow_run(meeting.id)
            self.job_queue.enqueue_batch(workflow_run.id, payload.model_dump(mode="json"))
            return {
                "job_id": workflow_run.id,
                "workflow_run_id": workflow_run.id,
                "meeting_id": meeting.id,
                "status": WorkflowStatus.PENDING.value,
            }
        return self.run_batch_workflow(payload=payload)

    def run_batch_workflow(
        self,
        workflow_run_id: int | None = None,
        payload: BatchMeetingRequest | dict[str, Any] | None = None,
    ) -> dict[str, object]:
        if isinstance(payload, dict):
            payload = BatchMeetingRequest.model_validate(payload)
        if payload is None:
            raise ValueError("Batch meeting payload is required.")

        if workflow_run_id is None:
            user = self.repository.get_or_create_user(payload.user_external_id, payload.user_email)
            transcript = self.asr.transcribe(payload.source_uri, payload.transcript_text)
            transcript_text = transcript.rendered_text()
            meeting = self.repository.create_meeting(user.id, payload.title, payload.source_uri, transcript_text)
            workflow_run = self.repository.create_workflow_run(meeting.id)
        else:
            workflow_run = self.repository.get_workflow_run(workflow_run_id)
            if workflow_run is None:
                raise ValueError(f"Workflow run {workflow_run_id} not found")
            meeting = self.repository.get_meeting(workflow_run.meeting_id)
            if meeting is None:
                raise ValueError(f"Meeting {workflow_run.meeting_id} not found")
            user = self.repository.get_user_by_id(meeting.user_id)
            if user is None:
                raise ValueError(f"User {meeting.user_id} not found")
            transcript = self.asr.transcribe(payload.source_uri, payload.transcript_text)
            transcript_text = transcript.rendered_text()
            self.repository.update_meeting_transcript(meeting.id, transcript_text)

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

    def get_workflow_status(self, workflow_run_id: int) -> WorkflowStatusResponse:
        workflow_run = self.repository.get_workflow_run(workflow_run_id)
        if workflow_run is None:
            raise ValueError(f"Workflow run {workflow_run_id} not found")

        meeting = self.repository.get_meeting(workflow_run.meeting_id)
        if meeting is None:
            raise ValueError(f"Meeting {workflow_run.meeting_id} not found")

        tool_executions: list[WorkflowToolExecutionRecord] = []
        tasks_created: int | None = None
        decisions_logged: int | None = None
        tool_calls_recorded: int | None = None

        if workflow_run.status in {
            WorkflowStatus.DONE,
            WorkflowStatus.AWAITING_APPROVAL,
            WorkflowStatus.FAILED,
        }:
            executions = self.repository.list_tool_executions(workflow_run_id)
            tool_executions = [
                WorkflowToolExecutionRecord(
                    tool_name=execution.tool_name,
                    status=execution.status.value,
                    attempts=self.repository.count_tool_execution_attempts(execution.id),
                    idempotency_key=execution.idempotency_key,
                    result=json.loads(execution.result) if execution.result else None,
                )
                for execution in executions
            ]
            tasks_created = len(self.repository.get_tasks_for_meeting(meeting.id))
            decisions_logged = len(
                [decision for decision in self.repository.get_decisions_for_user(meeting.user_id) if decision.meeting_id == meeting.id]
            )
            tool_calls_recorded = sum(
                1 for item in tool_executions if item.status in {"executed", "approval_required"}
            )

        return WorkflowStatusResponse(
            workflow_run_id=workflow_run.id,
            meeting_id=meeting.id,
            status=workflow_run.status.value,
            failure_reason=workflow_run.failure_reason,
            iteration_count=workflow_run.iteration_count,
            summary=meeting.summary_text or None,
            tasks_created=tasks_created,
            decisions_logged=decisions_logged,
            tool_calls_recorded=tool_calls_recorded,
            tool_executions=tool_executions,
        )

    def process_batch_meeting(self, payload: BatchMeetingRequest) -> dict[str, object]:
        return self.submit_batch_meeting(payload)

    def to_batch_response(self, result: dict[str, object]) -> BatchMeetingResponse:
        return BatchMeetingResponse.model_validate(result)
