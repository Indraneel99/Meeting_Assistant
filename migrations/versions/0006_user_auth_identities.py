"""Add user_auth_identities table for Phase 15 login credentials.

Revision ID: 0006_user_auth_identities
Revises: 0005_user_integrations
Create Date: 2026-08-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_user_auth_identities"
down_revision = "0005_user_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_auth_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("email_password", "google", name="authprovider"),
            nullable=False,
        ),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_subject"),
    )
    op.create_index("ix_user_auth_identities_user_id", "user_auth_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_auth_identities_user_id", table_name="user_auth_identities")
    op.drop_table("user_auth_identities")
    op.execute("DROP TYPE IF EXISTS authprovider")
