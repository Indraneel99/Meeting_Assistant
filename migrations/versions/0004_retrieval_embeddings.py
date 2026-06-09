"""Add chunk and decision embeddings for semantic retrieval.

Revision ID: 0004_retrieval_embeddings
Revises: 0003_approval_requests
Create Date: 2026-06-09 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_retrieval_embeddings"
down_revision = "0003_approval_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.add_column("meeting_chunks", sa.Column("chunk_embedding", sa.Text(), nullable=True))
        op.add_column("decisions", sa.Column("topic_embedding", sa.Text(), nullable=True))
        op.execute(
            """
            ALTER TABLE meeting_chunks
            ALTER COLUMN chunk_embedding TYPE vector(1536)
            USING CASE
                WHEN chunk_embedding IN ('[]', '') OR chunk_embedding IS NULL THEN NULL
                ELSE chunk_embedding::vector
            END
            """
        )
        op.execute(
            """
            ALTER TABLE decisions
            ALTER COLUMN topic_embedding TYPE vector(1536)
            USING CASE
                WHEN topic_embedding IN ('[]', '') OR topic_embedding IS NULL THEN NULL
                ELSE topic_embedding::vector
            END
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_meeting_chunks_chunk_embedding_hnsw
            ON meeting_chunks USING hnsw (chunk_embedding vector_cosine_ops)
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_decisions_topic_embedding_hnsw
            ON decisions USING hnsw (topic_embedding vector_cosine_ops)
            """
        )
        return

    op.add_column("meeting_chunks", sa.Column("chunk_embedding", sa.Text(), nullable=True))
    op.add_column("decisions", sa.Column("topic_embedding", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_decisions_topic_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_meeting_chunks_chunk_embedding_hnsw")
        op.execute(
            """
            ALTER TABLE decisions
            ALTER COLUMN topic_embedding TYPE TEXT
            USING COALESCE(topic_embedding::text, '[]')
            """
        )
        op.execute(
            """
            ALTER TABLE meeting_chunks
            ALTER COLUMN chunk_embedding TYPE TEXT
            USING COALESCE(chunk_embedding::text, '[]')
            """
        )
    op.drop_column("decisions", "topic_embedding")
    op.drop_column("meeting_chunks", "chunk_embedding")
