from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from meeting_assistant.db.models import (
    AgentStep,
    ApprovalRequest,
    ApprovalRequestStatus,
    Decision,
    Meeting,
    MeetingChunk,
    TaskItem,
    ToolExecution,
    ToolExecutionAttempt,
    ToolExecutionStatus,
    TranscriptArtifact,
    TranscriptSegment,
    User,
    WorkflowRun,
    WorkflowStatus,
)
from meeting_assistant.services.asr import TranscriptDocument


SessionFactory = Callable[[], Session]


@dataclass(slots=True)
class Repository:
    session_factory: SessionFactory

    def get_or_create_user(self, external_id: str, email: str) -> User:
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.external_id == external_id))
            if user:
                return user

            user = User(external_id=external_id, email=email)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def create_meeting(self, user_id: int, title: str, source_uri: str | None, transcript_text: str) -> Meeting:
        with self.session_factory() as session:
            meeting = Meeting(
                user_id=user_id,
                title=title,
                source_uri=source_uri,
                transcript_text=transcript_text,
            )
            session.add(meeting)
            session.commit()
            session.refresh(meeting)
            return meeting

    def create_workflow_run(self, meeting_id: int) -> WorkflowRun:
        with self.session_factory() as session:
            run = WorkflowRun(meeting_id=meeting_id)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def update_workflow_status(self, workflow_run_id: int, status: WorkflowStatus, failure_reason: str | None = None) -> WorkflowRun:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, workflow_run_id)
            if run is None:
                raise ValueError(f"Workflow run {workflow_run_id} not found")
            run.status = status
            run.failure_reason = failure_reason
            session.commit()
            session.refresh(run)
            return run

    def update_workflow_iteration_count(self, workflow_run_id: int, iteration_count: int) -> WorkflowRun:
        with self.session_factory() as session:
            run = session.get(WorkflowRun, workflow_run_id)
            if run is None:
                raise ValueError(f"Workflow run {workflow_run_id} not found")
            run.iteration_count = iteration_count
            session.commit()
            session.refresh(run)
            return run

    def replace_chunks(self, meeting_id: int, chunks: Sequence[tuple[str, list[float]]]) -> None:
        with self.session_factory() as session:
            session.query(MeetingChunk).filter(MeetingChunk.meeting_id == meeting_id).delete()
            for index, (text, embedding) in enumerate(chunks):
                session.add(
                    MeetingChunk(
                        meeting_id=meeting_id,
                        chunk_index=index,
                        text=text,
                        chunk_embedding=embedding,
                    )
                )
            session.commit()

    def save_transcript_artifact(self, meeting_id: int, transcript: TranscriptDocument) -> None:
        with self.session_factory() as session:
            artifact = session.scalar(
                select(TranscriptArtifact).where(TranscriptArtifact.meeting_id == meeting_id)
            )

            if artifact is None:
                artifact = TranscriptArtifact(
                    meeting_id=meeting_id,
                    provider=transcript.provider,
                    model_name=transcript.model_name,
                    source_uri=transcript.source_uri,
                    language=transcript.language,
                    duration_seconds=transcript.duration_seconds,
                    raw_text=transcript.text,
                    rendered_text=transcript.rendered_text(),
                    metadata_json=json.dumps(transcript.metadata),
                )
                session.add(artifact)
            else:
                artifact.provider = transcript.provider
                artifact.model_name = transcript.model_name
                artifact.source_uri = transcript.source_uri
                artifact.language = transcript.language
                artifact.duration_seconds = transcript.duration_seconds
                artifact.raw_text = transcript.text
                artifact.rendered_text = transcript.rendered_text()
                artifact.metadata_json = json.dumps(transcript.metadata)

            session.flush()

            session.query(TranscriptSegment).filter(TranscriptSegment.artifact_id == artifact.id).delete()
            for index, segment in enumerate(transcript.segments):
                session.add(
                    TranscriptSegment(
                        artifact_id=artifact.id,
                        segment_index=index,
                        speaker=segment.speaker,
                        start_seconds=segment.start_seconds,
                        end_seconds=segment.end_seconds,
                        text=segment.text,
                        confidence=segment.confidence,
                    )
                )

            session.commit()

    def complete_meeting(
        self,
        meeting_id: int,
        summary_text: str,
        summary_embedding: list[float],
        tasks: Sequence[dict[str, str]],
        decisions: Sequence[dict[str, str]],
    ) -> Meeting:
        with self.session_factory() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting is None:
                raise ValueError(f"Meeting {meeting_id} not found")

            meeting.summary_text = summary_text
            meeting.summary_embedding = summary_embedding

            session.query(TaskItem).filter(TaskItem.meeting_id == meeting_id).delete()
            session.query(Decision).filter(Decision.meeting_id == meeting_id).delete()

            for task in tasks:
                session.add(TaskItem(meeting_id=meeting_id, assignee=task["assignee"], action=task["action"]))

            for decision in decisions:
                session.add(
                    Decision(
                        meeting_id=meeting_id,
                        topic=decision["topic"],
                        decision_text=decision["decision_text"],
                        topic_embedding=decision.get("topic_embedding", []),
                    )
                )

            session.commit()
            session.refresh(meeting)
            return meeting

    def get_workflow_run(self, workflow_run_id: int) -> WorkflowRun | None:
        with self.session_factory() as session:
            return session.get(WorkflowRun, workflow_run_id)

    def get_user_by_id(self, user_id: int) -> User | None:
        with self.session_factory() as session:
            return session.get(User, user_id)

    def update_meeting_transcript(self, meeting_id: int, transcript_text: str) -> Meeting:
        with self.session_factory() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting is None:
                raise ValueError(f"Meeting {meeting_id} not found")
            meeting.transcript_text = transcript_text
            session.commit()
            session.refresh(meeting)
            return meeting

    def create_tool_execution(
        self,
        workflow_run_id: int,
        tool_name: str,
        payload: str,
        idempotency_key: str,
        status: str,
        result: str | None,
    ) -> ToolExecution:
        with self.session_factory() as session:
            existing = session.scalar(
                select(ToolExecution).where(
                    ToolExecution.workflow_run_id == workflow_run_id,
                    ToolExecution.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing

            execution = ToolExecution(
                workflow_run_id=workflow_run_id,
                tool_name=tool_name,
                payload=payload,
                idempotency_key=idempotency_key,
                status=status,
                result=result,
            )
            session.add(execution)
            session.commit()
            session.refresh(execution)
            return execution

    def get_tool_execution(self, workflow_run_id: int, idempotency_key: str) -> ToolExecution | None:
        with self.session_factory() as session:
            statement = select(ToolExecution).where(
                ToolExecution.workflow_run_id == workflow_run_id,
                ToolExecution.idempotency_key == idempotency_key,
            )
            return session.scalar(statement)

    def update_tool_execution(
        self,
        execution_id: int,
        *,
        status: ToolExecutionStatus,
        result: str | None,
    ) -> ToolExecution:
        with self.session_factory() as session:
            execution = session.get(ToolExecution, execution_id)
            if execution is None:
                raise ValueError(f"Tool execution {execution_id} not found")
            execution.status = status
            execution.result = result
            session.commit()
            session.refresh(execution)
            return execution

    def create_tool_execution_attempt(
        self,
        tool_execution_id: int,
        attempt_number: int,
        status: str,
        result: str | None,
        error_message: str | None,
    ) -> ToolExecutionAttempt:
        with self.session_factory() as session:
            attempt = ToolExecutionAttempt(
                tool_execution_id=tool_execution_id,
                attempt_number=attempt_number,
                status=status,
                result=result,
                error_message=error_message,
            )
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
            return attempt

    def list_tool_executions(self, workflow_run_id: int) -> list[ToolExecution]:
        with self.session_factory() as session:
            statement = (
                select(ToolExecution)
                .where(ToolExecution.workflow_run_id == workflow_run_id)
                .order_by(ToolExecution.id.asc())
            )
            return list(session.scalars(statement))

    def create_agent_step(
        self,
        workflow_run_id: int,
        iteration: int,
        step_kind: str,
        status: str,
        payload_json: str,
        result_json: str,
    ) -> AgentStep:
        with self.session_factory() as session:
            step = AgentStep(
                workflow_run_id=workflow_run_id,
                iteration=iteration,
                step_kind=step_kind,
                status=status,
                payload_json=payload_json,
                result_json=result_json,
            )
            session.add(step)
            session.commit()
            session.refresh(step)
            return step

    def list_agent_steps(self, workflow_run_id: int) -> list[AgentStep]:
        with self.session_factory() as session:
            statement = (
                select(AgentStep)
                .where(AgentStep.workflow_run_id == workflow_run_id)
                .order_by(AgentStep.id.asc())
            )
            return list(session.scalars(statement))

    def count_tool_execution_attempts(self, tool_execution_id: int) -> int:
        with self.session_factory() as session:
            statement = select(func.count(ToolExecutionAttempt.id)).where(
                ToolExecutionAttempt.tool_execution_id == tool_execution_id
            )
            return int(session.scalar(statement) or 0)

    def get_tool_execution_by_id(self, execution_id: int) -> ToolExecution | None:
        with self.session_factory() as session:
            return session.get(ToolExecution, execution_id)

    def create_approval_request(
        self,
        workflow_run_id: int,
        tool_execution_id: int,
        tool_name: str,
        payload: str,
    ) -> ApprovalRequest:
        with self.session_factory() as session:
            existing = session.scalar(
                select(ApprovalRequest).where(ApprovalRequest.tool_execution_id == tool_execution_id)
            )
            if existing is not None:
                return existing

            request = ApprovalRequest(
                workflow_run_id=workflow_run_id,
                tool_execution_id=tool_execution_id,
                tool_name=tool_name,
                payload=payload,
                status=ApprovalRequestStatus.PENDING,
            )
            session.add(request)
            session.commit()
            session.refresh(request)
            return request

    def get_approval_request(self, approval_request_id: int) -> ApprovalRequest | None:
        with self.session_factory() as session:
            return session.get(ApprovalRequest, approval_request_id)

    def list_approval_requests(self, workflow_run_id: int) -> list[ApprovalRequest]:
        with self.session_factory() as session:
            statement = (
                select(ApprovalRequest)
                .where(ApprovalRequest.workflow_run_id == workflow_run_id)
                .order_by(ApprovalRequest.id.asc())
            )
            return list(session.scalars(statement))

    def resolve_approval_request(
        self,
        approval_request_id: int,
        *,
        status: ApprovalRequestStatus,
        resolved_by: str | None = None,
    ) -> ApprovalRequest:
        with self.session_factory() as session:
            request = session.get(ApprovalRequest, approval_request_id)
            if request is None:
                raise ValueError(f"Approval request {approval_request_id} not found")
            request.status = status
            request.resolved_by = resolved_by
            request.resolved_at = datetime.now(UTC)
            session.commit()
            session.refresh(request)
            return request

    def update_agent_step_for_tool(self, workflow_run_id: int, tool_name: str, status: str) -> None:
        with self.session_factory() as session:
            statement = (
                select(AgentStep)
                .where(
                    AgentStep.workflow_run_id == workflow_run_id,
                    AgentStep.step_kind == "tool",
                )
                .order_by(AgentStep.id.desc())
            )
            for step in session.scalars(statement):
                payload = json.loads(step.payload_json)
                if payload.get("tool_name") == tool_name and step.status == "approval_required":
                    step.status = status
                    session.commit()
                    return

    def list_recent_meetings(self, user_id: int, limit: int) -> list[Meeting]:
        with self.session_factory() as session:
            statement = (
                select(Meeting)
                .where(Meeting.user_id == user_id, Meeting.summary_text != "")
                .order_by(desc(Meeting.created_at))
                .limit(limit)
            )
            return list(session.scalars(statement))

    def get_meeting(self, meeting_id: int) -> Meeting | None:
        with self.session_factory() as session:
            return session.get(Meeting, meeting_id)

    def get_user_by_external_id(self, external_id: str) -> User | None:
        with self.session_factory() as session:
            return session.scalar(select(User).where(User.external_id == external_id))

    def get_meetings_for_user(self, user_id: int) -> list[Meeting]:
        with self.session_factory() as session:
            statement = select(Meeting).where(Meeting.user_id == user_id, Meeting.summary_text != "")
            return list(session.scalars(statement))

    def get_tasks_for_meeting(self, meeting_id: int) -> list[TaskItem]:
        with self.session_factory() as session:
            statement = select(TaskItem).where(TaskItem.meeting_id == meeting_id)
            return list(session.scalars(statement))

    def get_decisions_for_user(self, user_id: int) -> list[Decision]:
        with self.session_factory() as session:
            statement = select(Decision).join(Meeting).where(Meeting.user_id == user_id)
            return list(session.scalars(statement))

    def get_chunks_for_user(self, user_id: int) -> list[tuple[MeetingChunk, str]]:
        with self.session_factory() as session:
            statement = (
                select(MeetingChunk, Meeting.title)
                .join(Meeting)
                .where(Meeting.user_id == user_id)
            )
            return [(chunk, title) for chunk, title in session.execute(statement)]

    def search_chunks_by_embedding(
        self,
        user_id: int,
        query_embedding: list[float],
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        from meeting_assistant.services.retrieval_pagination import decode_cursor, encode_cursor

        with self.session_factory() as session:
            distance_expr = MeetingChunk.chunk_embedding.cosine_distance(query_embedding)
            statement = (
                select(MeetingChunk, Meeting.title, distance_expr.label("distance"))
                .join(Meeting)
                .where(
                    Meeting.user_id == user_id,
                    MeetingChunk.chunk_embedding.is_not(None),
                )
                .order_by(distance_expr, MeetingChunk.id.desc())
            )
            if cursor:
                cursor_score, cursor_id = decode_cursor(cursor)
                statement = statement.where(
                    (distance_expr > (1.0 - cursor_score))
                    | (
                        (distance_expr == (1.0 - cursor_score))
                        & (MeetingChunk.id < cursor_id)
                    )
                )

            rows = list(session.execute(statement.limit(limit + 1)))
            results: list[dict[str, object]] = []
            for chunk, title, distance in rows:
                score = max(0.0, 1.0 - float(distance))
                if score <= 0:
                    continue
                results.append(
                    {
                        "chunk_id": chunk.id,
                        "meeting_id": chunk.meeting_id,
                        "meeting_title": title,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "score": round(score, 4),
                    }
                )

            has_more = len(results) > limit
            page = results[:limit]
            next_cursor = None
            if has_more and page:
                last = page[-1]
                next_cursor = encode_cursor(float(last["score"]), int(last["chunk_id"]))
            return page, next_cursor, has_more

    def search_decisions_by_embedding(
        self,
        user_id: int,
        query_embedding: list[float],
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        from meeting_assistant.services.retrieval_pagination import decode_cursor, encode_cursor

        with self.session_factory() as session:
            distance_expr = Decision.topic_embedding.cosine_distance(query_embedding)
            statement = (
                select(Decision, distance_expr.label("distance"))
                .join(Meeting)
                .where(
                    Meeting.user_id == user_id,
                    Decision.topic_embedding.is_not(None),
                )
                .order_by(distance_expr, Decision.id.desc())
            )
            if cursor:
                cursor_score, cursor_id = decode_cursor(cursor)
                statement = statement.where(
                    (distance_expr > (1.0 - cursor_score))
                    | (
                        (distance_expr == (1.0 - cursor_score))
                        & (Decision.id < cursor_id)
                    )
                )

            rows = list(session.execute(statement.limit(limit + 1)))
            results: list[dict[str, object]] = []
            for decision, distance in rows:
                score = max(0.0, 1.0 - float(distance))
                if score <= 0:
                    continue
                results.append(
                    {
                        "decision_id": decision.id,
                        "meeting_id": decision.meeting_id,
                        "topic": decision.topic,
                        "decision_text": decision.decision_text,
                        "score": round(score, 4),
                    }
                )

            has_more = len(results) > limit
            page = results[:limit]
            next_cursor = None
            if has_more and page:
                last = page[-1]
                next_cursor = encode_cursor(float(last["score"]), int(last["decision_id"]))
            return page, next_cursor, has_more

    def search_meetings_by_embedding(
        self,
        user_id: int,
        query_embedding: list[float],
        limit: int,
        *,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, object]], str | None, bool]:
        from meeting_assistant.services.retrieval_pagination import decode_cursor, encode_cursor

        with self.session_factory() as session:
            distance_expr = Meeting.summary_embedding.cosine_distance(query_embedding)
            statement = (
                select(Meeting, distance_expr.label("distance"))
                .where(
                    Meeting.user_id == user_id,
                    Meeting.summary_text != "",
                    Meeting.summary_embedding.is_not(None),
                )
                .order_by(distance_expr, Meeting.id.desc())
            )
            if cursor:
                cursor_score, cursor_id = decode_cursor(cursor)
                statement = statement.where(
                    (distance_expr > (1.0 - cursor_score))
                    | (
                        (distance_expr == (1.0 - cursor_score))
                        & (Meeting.id < cursor_id)
                    )
                )

            rows = list(session.execute(statement.limit(limit + 1)))
            results: list[dict[str, object]] = []
            for meeting, distance in rows:
                score = max(0.0, 1.0 - float(distance))
                if score <= 0:
                    continue
                results.append(
                    {
                        "meeting_id": meeting.id,
                        "title": meeting.title,
                        "summary": meeting.summary_text,
                        "score": round(score, 4),
                    }
                )

            has_more = len(results) > limit
            page = results[:limit]
            next_cursor = None
            if has_more and page:
                last = page[-1]
                next_cursor = encode_cursor(float(last["score"]), int(last["meeting_id"]))
            return page, next_cursor, has_more
