"""Add user_integrations table for Phase 13 per-user OAuth and preferences.

Revision ID: 0005_user_integrations
Revises: 0004_retrieval_embeddings
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_user_integrations"
down_revision = "0004_retrieval_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("slack", "google", "jira", "email_prefs", name="integrationprovider"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("connected", "revoked", "expired", "error", name="integrationstatus"),
            nullable=False,
            server_default="connected",
        ),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_account_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("settings_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "provider", "provider_account_id"),
    )
    op.create_index("ix_user_integrations_user_id", "user_integrations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_integrations_user_id", table_name="user_integrations")
    op.drop_table("user_integrations")
