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
    AuthProvider,
    Decision,
    IntegrationProvider,
    IntegrationStatus,
    Meeting,
    MeetingChunk,
    TaskItem,
    ToolExecution,
    ToolExecutionAttempt,
    ToolExecutionStatus,
    TranscriptArtifact,
    TranscriptSegment,
    User,
    UserAuthIdentity,
    UserIntegration,
    WorkflowRun,
    WorkflowStatus,
)
from meeting_assistant.services.asr import TranscriptDocument
from meeting_assistant.services.auth_identity import generate_user_external_id, normalize_auth_email
from meeting_assistant.services.token_encryption import TokenEncryptor

SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class StaleWorkflowRow:
    workflow_run_id: int
    meeting_id: int
    user_external_id: str | None
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FailedToolRow:
    tool_execution_id: int
    workflow_run_id: int
    meeting_id: int
    user_external_id: str | None
    tool_name: str
    status: str
    result: str | None
    attempt_count: int
    error_message: str | None
    last_attempt_at: datetime | None


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

    def get_user_external_id_for_workflow(self, workflow_run_id: int) -> str | None:
        with self.session_factory() as session:
            statement = (
                select(User.external_id)
                .join(Meeting, Meeting.user_id == User.id)
                .join(WorkflowRun, WorkflowRun.meeting_id == Meeting.id)
                .where(WorkflowRun.id == workflow_run_id)
            )
            return session.scalar(statement)

    def get_user_external_id_for_approval(self, approval_request_id: int) -> str | None:
        with self.session_factory() as session:
            statement = (
                select(User.external_id)
                .join(Meeting, Meeting.user_id == User.id)
                .join(WorkflowRun, WorkflowRun.meeting_id == Meeting.id)
                .join(ApprovalRequest, ApprovalRequest.workflow_run_id == WorkflowRun.id)
                .where(ApprovalRequest.id == approval_request_id)
            )
            return session.scalar(statement)

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

    def get_user_by_email(self, email: str) -> User | None:
        normalized = normalize_auth_email(email)
        with self.session_factory() as session:
            return session.scalar(select(User).where(User.email == normalized))

    def get_auth_identity(
        self,
        provider: AuthProvider,
        provider_subject: str,
    ) -> UserAuthIdentity | None:
        with self.session_factory() as session:
            return session.scalar(
                select(UserAuthIdentity).where(
                    UserAuthIdentity.provider == provider,
                    UserAuthIdentity.provider_subject == provider_subject,
                )
            )

    def list_auth_identities_for_user(self, user_id: int) -> list[UserAuthIdentity]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(UserAuthIdentity)
                    .where(UserAuthIdentity.user_id == user_id)
                    .order_by(UserAuthIdentity.provider, UserAuthIdentity.provider_subject)
                )
            )

    def create_user_with_auth_identity(
        self,
        *,
        email: str,
        provider: AuthProvider,
        provider_subject: str,
        password_hash: str | None = None,
        metadata_json: dict[str, object] | None = None,
        external_id: str | None = None,
    ) -> tuple[User, UserAuthIdentity]:
        normalized_email = normalize_auth_email(email)
        with self.session_factory() as session:
            user = User(
                external_id=external_id or generate_user_external_id(),
                email=normalized_email,
            )
            session.add(user)
            session.flush()

            identity = UserAuthIdentity(
                user_id=user.id,
                provider=provider,
                provider_subject=provider_subject,
                password_hash=password_hash,
                metadata_json=metadata_json or {},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(identity)
            session.commit()
            session.refresh(user)
            session.refresh(identity)
            return user, identity

    def link_auth_identity_to_user(
        self,
        user_id: int,
        *,
        provider: AuthProvider,
        provider_subject: str,
        password_hash: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> UserAuthIdentity:
        with self.session_factory() as session:
            identity = UserAuthIdentity(
                user_id=user_id,
                provider=provider,
                provider_subject=provider_subject,
                password_hash=password_hash,
                metadata_json=metadata_json or {},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(identity)
            session.commit()
            session.refresh(identity)
            return identity

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

    def upsert_user_integration(
        self,
        *,
        encryptor: TokenEncryptor,
        user_id: int,
        provider: IntegrationProvider,
        provider_account_id: str = "",
        status: IntegrationStatus = IntegrationStatus.CONNECTED,
        scopes: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: datetime | None = None,
        settings_json: dict[str, object] | None = None,
    ) -> UserIntegration:
        with self.session_factory() as session:
            integration = session.scalar(
                select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == provider,
                    UserIntegration.provider_account_id == provider_account_id,
                )
            )
            now = datetime.now(UTC)
            if integration is None:
                integration = UserIntegration(
                    user_id=user_id,
                    provider=provider,
                    provider_account_id=provider_account_id,
                    connected_at=now,
                )
                session.add(integration)

            integration.status = status
            integration.scopes = scopes
            if access_token is not None:
                integration.access_token_enc = encryptor.encrypt(access_token)
            if refresh_token is not None:
                integration.refresh_token_enc = encryptor.encrypt(refresh_token)
            integration.expires_at = expires_at
            if settings_json is not None:
                integration.settings_json = settings_json
            integration.updated_at = now
            session.commit()
            session.refresh(integration)
            return integration

    def get_user_integration(
        self,
        user_id: int,
        provider: IntegrationProvider,
        *,
        provider_account_id: str = "",
    ) -> UserIntegration | None:
        with self.session_factory() as session:
            return session.scalar(
                select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == provider,
                    UserIntegration.provider_account_id == provider_account_id,
                )
            )

    def list_user_integrations(self, user_id: int) -> list[UserIntegration]:
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(UserIntegration)
                    .where(UserIntegration.user_id == user_id)
                    .order_by(UserIntegration.provider, UserIntegration.provider_account_id)
                )
            )

    def update_user_integration_settings(
        self,
        user_id: int,
        provider: IntegrationProvider,
        settings_json: dict[str, object],
        *,
        provider_account_id: str = "",
    ) -> UserIntegration:
        with self.session_factory() as session:
            integration = session.scalar(
                select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == provider,
                    UserIntegration.provider_account_id == provider_account_id,
                )
            )
            if integration is None:
                raise ValueError(
                    f"Integration {provider.value} not found for user {user_id} "
                    f"(account {provider_account_id!r})"
                )
            integration.settings_json = settings_json
            integration.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(integration)
            return integration

    def revoke_user_integration(
        self,
        user_id: int,
        provider: IntegrationProvider,
        *,
        provider_account_id: str = "",
    ) -> UserIntegration:
        with self.session_factory() as session:
            integration = session.scalar(
                select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == provider,
                    UserIntegration.provider_account_id == provider_account_id,
                )
            )
            if integration is None:
                raise ValueError(
                    f"Integration {provider.value} not found for user {user_id} "
                    f"(account {provider_account_id!r})"
                )
            integration.status = IntegrationStatus.REVOKED
            integration.access_token_enc = None
            integration.refresh_token_enc = None
            integration.expires_at = None
            integration.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(integration)
            return integration

    def get_user_id_for_workflow(self, workflow_run_id: int) -> int | None:
        with self.session_factory() as session:
            return session.scalar(
                select(Meeting.user_id)
                .join(WorkflowRun, WorkflowRun.meeting_id == Meeting.id)
                .where(WorkflowRun.id == workflow_run_id)
            )

    def get_connected_integration(
        self,
        user_id: int,
        provider: IntegrationProvider,
    ) -> UserIntegration | None:
        with self.session_factory() as session:
            return session.scalar(
                select(UserIntegration)
                .where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == provider,
                    UserIntegration.status == IntegrationStatus.CONNECTED,
                )
                .order_by(UserIntegration.connected_at.desc())
            )

    def decrypt_integration_tokens(
        self,
        integration: UserIntegration,
        *,
        encryptor: TokenEncryptor,
    ) -> tuple[str | None, str | None]:
        return (
            encryptor.decrypt(integration.access_token_enc),
            encryptor.decrypt(integration.refresh_token_enc),
        )

    def list_stale_pending_workflows(
        self,
        *,
        older_than: datetime,
        limit: int = 100,
    ) -> list[StaleWorkflowRow]:
        with self.session_factory() as session:
            rows = session.execute(
                select(
                    WorkflowRun.id,
                    WorkflowRun.meeting_id,
                    User.external_id,
                    WorkflowRun.status,
                    WorkflowRun.created_at,
                )
                .join(Meeting, Meeting.id == WorkflowRun.meeting_id)
                .join(User, User.id == Meeting.user_id)
                .where(
                    WorkflowRun.status == WorkflowStatus.PENDING,
                    WorkflowRun.created_at <= older_than,
                )
                .order_by(WorkflowRun.created_at.asc())
                .limit(limit)
            ).all()
            return [
                StaleWorkflowRow(
                    workflow_run_id=row[0],
                    meeting_id=row[1],
                    user_external_id=row[2],
                    status=row[3].value if hasattr(row[3], "value") else str(row[3]),
                    created_at=row[4],
                )
                for row in rows
            ]

    def list_failed_tool_executions(
        self,
        *,
        since: datetime,
        limit: int = 100,
    ) -> list[FailedToolRow]:
        attempt_stats = (
            select(
                ToolExecutionAttempt.tool_execution_id.label("tool_execution_id"),
                func.count(ToolExecutionAttempt.id).label("attempt_count"),
                func.max(ToolExecutionAttempt.created_at).label("last_attempt_at"),
            )
            .group_by(ToolExecutionAttempt.tool_execution_id)
            .subquery()
        )
        with self.session_factory() as session:
            rows = session.execute(
                select(
                    ToolExecution.id,
                    ToolExecution.workflow_run_id,
                    Meeting.id,
                    User.external_id,
                    ToolExecution.tool_name,
                    ToolExecution.status,
                    ToolExecution.result,
                    attempt_stats.c.attempt_count,
                    attempt_stats.c.last_attempt_at,
                )
                .join(WorkflowRun, WorkflowRun.id == ToolExecution.workflow_run_id)
                .join(Meeting, Meeting.id == WorkflowRun.meeting_id)
                .join(User, User.id == Meeting.user_id)
                .join(attempt_stats, attempt_stats.c.tool_execution_id == ToolExecution.id)
                .where(
                    ToolExecution.status == ToolExecutionStatus.FAILED,
                    attempt_stats.c.last_attempt_at >= since,
                )
                .order_by(attempt_stats.c.last_attempt_at.desc())
                .limit(limit)
            ).all()
            return [
                FailedToolRow(
                    tool_execution_id=row[0],
                    workflow_run_id=row[1],
                    meeting_id=row[2],
                    user_external_id=row[3],
                    tool_name=row[4],
                    status=row[5].value if hasattr(row[5], "value") else str(row[5]),
                    result=row[6],
                    attempt_count=int(row[7]),
                    error_message=None,
                    last_attempt_at=row[8],
                )
                for row in rows
            ]
