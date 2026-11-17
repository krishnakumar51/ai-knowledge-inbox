"""Initial item and chunk schema."""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    source_type = sa.Enum("note", "url", name="source_type")
    item_status = sa.Enum("processing", "ready", "failed", name="item_status")
    op.create_table(
        "items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("status", item_status, nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_items_source_type", "items", ["source_type"])
    op.create_index("ix_items_status", "items", ["status"])
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("item_id", sa.UUID(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("item_id", "chunk_index", name="ix_chunks_item_id_chunk_index"),
    )
    op.create_index("ix_chunks_item_id", "chunks", ["item_id"])
    op.execute("CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ix_chunks_content_fts ON chunks USING gin (to_tsvector('english', content))")


def downgrade():
    op.drop_table("chunks")
    op.drop_table("items")
    sa.Enum(name="item_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="source_type").drop(op.get_bind(), checkfirst=True)
