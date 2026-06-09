from __future__ import annotations

import json
from dataclasses import dataclass

from meeting_assistant.db.models import ApprovalRequestStatus, WorkflowStatus
from meeting_assistant.repositories import Repository
from meeting_assistant.schemas.approval import ApprovalRequestResponse, ApprovalResolutionResponse
from meeting_assistant.services.agent import AgentRuntime
from meeting_assistant.services.context import ContextLoader
from meeting_assistant.services.embeddings import EmbeddingIndex
from meeting_assistant.services.tools import ToolExecutor


@dataclass(slots=True)
class ApprovalService:
    repository: Repository
    tool_executor: ToolExecutor
    agent_runtime: AgentRuntime
    context_loader: ContextLoader
    embedding_index: EmbeddingIndex

    def list_workflow_approvals(self, workflow_run_id: int) -> list[ApprovalRequestResponse]:
        workflow_run = self.repository.get_workflow_run(workflow_run_id)
        if workflow_run is None:
            raise ValueError(f"Workflow run {workflow_run_id} not found")

        return [
            self._to_response(request)
            for request in self.repository.list_approval_requests(workflow_run_id)
        ]

    def approve(self, approval_request_id: int, *, resolved_by: str | None = None) -> ApprovalResolutionResponse:
        return self._resolve(approval_request_id, approved=True, resolved_by=resolved_by)

    def reject(self, approval_request_id: int, *, resolved_by: str | None = None) -> ApprovalResolutionResponse:
        return self._resolve(approval_request_id, approved=False, resolved_by=resolved_by)

    def _resolve(
        self,
        approval_request_id: int,
        *,
        approved: bool,
        resolved_by: str | None,
    ) -> ApprovalResolutionResponse:
        request = self.repository.get_approval_request(approval_request_id)
        if request is None:
            raise ValueError(f"Approval request {approval_request_id} not found")
        if request.status != ApprovalRequestStatus.PENDING:
            raise ValueError(f"Approval request {approval_request_id} is already {request.status.value}.")

        workflow_run = self.repository.get_workflow_run(request.workflow_run_id)
        if workflow_run is None:
            raise ValueError(f"Workflow run {request.workflow_run_id} not found")
        if workflow_run.status != WorkflowStatus.AWAITING_APPROVAL:
            raise ValueError(f"Workflow run {request.workflow_run_id} is not awaiting approval.")

        outcome = self.tool_executor.finalize_approval(request.tool_execution_id, approved=approved)
        self.repository.resolve_approval_request(
            approval_request_id,
            status=ApprovalRequestStatus.APPROVED if approved else ApprovalRequestStatus.REJECTED,
            resolved_by=resolved_by,
        )
        self.repository.update_agent_step_for_tool(
            request.workflow_run_id,
            request.tool_name,
            outcome.status,
        )

        meeting = self.repository.get_meeting(workflow_run.meeting_id)
        if meeting is None:
            raise ValueError(f"Meeting {workflow_run.meeting_id} not found")

        self.repository.update_workflow_status(request.workflow_run_id, WorkflowStatus.EXECUTING)
        context = self.context_loader.load(meeting.user_id, meeting.transcript_text)
        agent_result = self.agent_runtime.resume(
            workflow_run_id=request.workflow_run_id,
            title=meeting.title,
            transcript_text=meeting.transcript_text,
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
        self.repository.update_workflow_status(request.workflow_run_id, WorkflowStatus(agent_result.status))

        return ApprovalResolutionResponse(
            approval_request_id=approval_request_id,
            workflow_run_id=request.workflow_run_id,
            approval_status=ApprovalRequestStatus.APPROVED.value if approved else ApprovalRequestStatus.REJECTED.value,
            tool_status=outcome.status,
            tool_result=outcome.result,
            workflow_status=agent_result.status,
            summary=agent_result.summary,
            tool_executions=agent_result.tool_executions,
            iterations_used=agent_result.iterations_used,
        )

    def _to_response(self, request) -> ApprovalRequestResponse:
        return ApprovalRequestResponse(
            approval_request_id=request.id,
            workflow_run_id=request.workflow_run_id,
            tool_execution_id=request.tool_execution_id,
            tool_name=request.tool_name,
            payload=json.loads(request.payload),
            status=request.status.value,
            requested_at=request.requested_at,
            resolved_by=request.resolved_by,
            resolved_at=request.resolved_at,
        )
