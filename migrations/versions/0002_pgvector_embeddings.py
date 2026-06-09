"""Add pgvector column for meeting summary embeddings.

Revision ID: 0002_pgvector_embeddings
Revises: 0001_initial_schema
Create Date: 2026-06-09 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0002_pgvector_embeddings"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE meetings
        ALTER COLUMN summary_embedding TYPE vector(1536)
        USING CASE
            WHEN summary_embedding IN ('[]', '') THEN NULL
            ELSE summary_embedding::vector
        END
        """
    )
    op.alter_column("meetings", "summary_embedding", nullable=True)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_meetings_summary_embedding_hnsw
        ON meetings USING hnsw (summary_embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_meetings_summary_embedding_hnsw")
    op.execute(
        """
        ALTER TABLE meetings
        ALTER COLUMN summary_embedding TYPE TEXT
        USING COALESCE(summary_embedding::text, '[]')
        """
    )
    op.alter_column("meetings", "summary_embedding", nullable=False)
