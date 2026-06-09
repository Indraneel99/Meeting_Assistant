"""Add approval_requests table for human-in-the-loop tool gating.

Revision ID: 0003_approval_requests
Revises: 0002_pgvector_embeddings
Create Date: 2026-06-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_approval_requests"
down_revision = "0002_pgvector_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_run_id", sa.Integer(), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("tool_execution_id", sa.Integer(), sa.ForeignKey("tool_executions.id"), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="approvalrequeststatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tool_execution_id"),
    )
    op.create_index("ix_approval_requests_workflow_run_id", "approval_requests", ["workflow_run_id"])
    op.create_index("ix_approval_requests_tool_execution_id", "approval_requests", ["tool_execution_id"])


def downgrade() -> None:
    op.drop_index("ix_approval_requests_tool_execution_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_workflow_run_id", table_name="approval_requests")
    op.drop_table("approval_requests")
