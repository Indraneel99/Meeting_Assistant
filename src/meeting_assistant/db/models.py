from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"


class ToolExecutionStatus(StrEnum):
    PENDING = "pending"
    APPROVAL_REQUIRED = "approval_required"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meetings: Mapped[list["Meeting"]] = relationship(back_populates="user")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    transcript_text: Mapped[str] = mapped_column(Text)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    summary_embedding: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="meetings")
    chunks: Mapped[list["MeetingChunk"]] = relationship(back_populates="meeting")
    tasks: Mapped[list["TaskItem"]] = relationship(back_populates="meeting")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="meeting")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="meeting")
    transcript_artifact: Mapped["TranscriptArtifact | None"] = relationship(back_populates="meeting")


class MeetingChunk(Base):
    __tablename__ = "meeting_chunks"
    __table_args__ = (UniqueConstraint("meeting_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    meeting: Mapped["Meeting"] = relationship(back_populates="chunks")


class TranscriptArtifact(Base):
    __tablename__ = "transcript_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(128))
    model_name: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_seconds: Mapped[float | None]
    raw_text: Mapped[str] = mapped_column(Text)
    rendered_text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    meeting: Mapped["Meeting"] = relationship(back_populates="transcript_artifact")
    segments: Mapped[list["TranscriptSegment"]] = relationship(back_populates="artifact")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("artifact_id", "segment_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("transcript_artifacts.id"), index=True)
    segment_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_seconds: Mapped[float | None]
    end_seconds: Mapped[float | None]
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None]

    artifact: Mapped["TranscriptArtifact"] = relationship(back_populates="segments")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    status: Mapped[WorkflowStatus] = mapped_column(SqlEnum(WorkflowStatus), default=WorkflowStatus.PENDING)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)

    meeting: Mapped["Meeting"] = relationship(back_populates="workflow_runs")
    tool_executions: Mapped[list["ToolExecution"]] = relationship(back_populates="workflow_run")
    agent_steps: Mapped[list["AgentStep"]] = relationship(back_populates="workflow_run")


class TaskItem(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    assignee: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), default="open")

    meeting: Mapped["Meeting"] = relationship(back_populates="tasks")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), index=True)
    topic: Mapped[str] = mapped_column(String(255))
    decision_text: Mapped[str] = mapped_column(Text)

    meeting: Mapped["Meeting"] = relationship(back_populates="decisions")


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    __table_args__ = (UniqueConstraint("workflow_run_id", "idempotency_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(255))
    payload: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[ToolExecutionStatus] = mapped_column(
        SqlEnum(ToolExecutionStatus),
        default=ToolExecutionStatus.PENDING,
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True)

    workflow_run: Mapped["WorkflowRun"] = relationship(back_populates="tool_executions")
    attempts: Mapped[list["ToolExecutionAttempt"]] = relationship(back_populates="tool_execution")


class ToolExecutionAttempt(Base):
    __tablename__ = "tool_execution_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool_execution_id: Mapped[int] = mapped_column(ForeignKey("tool_executions.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(64))
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tool_execution: Mapped["ToolExecution"] = relationship(back_populates="attempts")


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    iteration: Mapped[int] = mapped_column(Integer)
    step_kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workflow_run: Mapped["WorkflowRun"] = relationship(back_populates="agent_steps")
