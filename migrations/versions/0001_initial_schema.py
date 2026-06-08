"""Create initial meeting assistant schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-08 18:15:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

workflow_status = sa.Enum(
    "PENDING",
    "VALIDATED",
    "EXECUTING",
    "AWAITING_APPROVAL",
    "DONE",
    "FAILED",
    name="workflowstatus",
)
tool_execution_status = sa.Enum(
    "PENDING",
    "APPROVAL_REQUIRED",
    "EXECUTED",
    "FAILED",
    "SKIPPED",
    name="toolexecutionstatus",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_external_id", "users", ["external_id"], unique=True)

    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_uri", sa.String(length=512), nullable=True),
        sa.Column("transcript_text", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("summary_embedding", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meetings_user_id", "meetings", ["user_id"], unique=False)

    op.create_table(
        "meeting_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meeting_id", "chunk_index", name="uq_meeting_chunks_meeting_chunk_index"),
    )
    op.create_index("ix_meeting_chunks_meeting_id", "meeting_chunks", ["meeting_id"], unique=False)

    op.create_table(
        "transcript_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("source_uri", sa.String(length=512), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("rendered_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcript_artifacts_meeting_id", "transcript_artifacts", ["meeting_id"], unique=True)

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=64), nullable=True),
        sa.Column("start_seconds", sa.Float(), nullable=True),
        sa.Column("end_seconds", sa.Float(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["transcript_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "segment_index", name="uq_transcript_segments_artifact_segment_index"),
    )
    op.create_index("ix_transcript_segments_artifact_id", "transcript_segments", ["artifact_id"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("status", workflow_status, nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iteration_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_meeting_id", "workflow_runs", ["meeting_id"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("assignee", sa.String(length=255), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_meeting_id", "tasks", ["meeting_id"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("decision_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_meeting_id", "decisions", ["meeting_id"], unique=False)

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", tool_execution_status, nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "idempotency_key", name="uq_tool_executions_workflow_idempotency"),
    )
    op.create_index("ix_tool_executions_workflow_run_id", "tool_executions", ["workflow_run_id"], unique=False)

    op.create_table(
        "tool_execution_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tool_execution_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tool_execution_id"], ["tool_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_execution_attempts_tool_execution_id",
        "tool_execution_attempts",
        ["tool_execution_id"],
        unique=False,
    )

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("step_kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_steps_workflow_run_id", "agent_steps", ["workflow_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_steps_workflow_run_id", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_tool_execution_attempts_tool_execution_id", table_name="tool_execution_attempts")
    op.drop_table("tool_execution_attempts")
    op.drop_index("ix_tool_executions_workflow_run_id", table_name="tool_executions")
    op.drop_table("tool_executions")
    op.drop_index("ix_decisions_meeting_id", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_tasks_meeting_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_workflow_runs_meeting_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_transcript_segments_artifact_id", table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_index("ix_transcript_artifacts_meeting_id", table_name="transcript_artifacts")
    op.drop_table("transcript_artifacts")
    op.drop_index("ix_meeting_chunks_meeting_id", table_name="meeting_chunks")
    op.drop_table("meeting_chunks")
    op.drop_index("ix_meetings_user_id", table_name="meetings")
    op.drop_table("meetings")
    op.drop_index("ix_users_external_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        tool_execution_status.drop(bind, checkfirst=True)
        workflow_status.drop(bind, checkfirst=True)
