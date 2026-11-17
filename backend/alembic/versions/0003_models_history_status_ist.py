"""Use OpenRouter 2048 vectors, item statuses, metadata, and revision snapshots."""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_models_history_status_ist"
down_revision = "0002_users_temporal_chat"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    chunk_count = bind.execute(sa.text("SELECT count(*) FROM chunks")).scalar_one()
    if chunk_count:
        raise RuntimeError(
            "Cannot change vector dimensions while chunks exist. Re-embed all stored chunks into a staged "
            "2048-dimensional column before applying this migration; no chunk data was changed."
        )

    op.drop_index("ix_chunks_embedding_hnsw", table_name="chunks")
    op.alter_column(
        "chunks",
        "embedding",
        type_=Vector(2048),
        existing_nullable=False,
        postgresql_using="embedding::vector(2048)",
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw "
        "((embedding::halfvec(2048)) halfvec_cosine_ops)"
    )

    op.execute("CREATE TYPE item_status_v2 AS ENUM ('ACTIVE','PROCESSING','FAILED','ARCHIVED')")
    op.execute(
        "ALTER TABLE items ALTER COLUMN status TYPE item_status_v2 USING "
        "(CASE status::text WHEN 'ready' THEN 'ACTIVE' WHEN 'processing' THEN 'PROCESSING' "
        "WHEN 'failed' THEN 'FAILED' END)::item_status_v2"
    )
    op.execute("DROP TYPE item_status")
    op.execute("ALTER TYPE item_status_v2 RENAME TO item_status")

    op.add_column(
        "items",
        sa.Column(
            "source_metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.add_column("items", sa.Column("dataset_id", sa.String(200), nullable=True))
    op.add_column("items", sa.Column("external_id", sa.String(250), nullable=True))
    op.create_unique_constraint(
        "uq_items_dataset_external", "items", ["user_id", "dataset_id", "external_id"]
    )

    change_type = postgresql.ENUM(
        "CREATED",
        "CONTENT_UPDATED",
        "METADATA_UPDATED",
        "URL_UPDATED",
        "RESTORED",
        name="revision_change_type",
        create_type=False,
    )
    change_type.create(bind, checkfirst=True)
    op.create_table(
        "item_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("title_snapshot", sa.String(500), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column(
            "source_type_snapshot",
            postgresql.ENUM("note", "url", name="source_type", create_type=False),
            nullable=False,
        ),
        sa.Column("source_url_snapshot", sa.Text()),
        sa.Column(
            "source_metadata_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("effective_at_snapshot", sa.DateTime(timezone=True)),
        sa.Column(
            "status_snapshot",
            postgresql.ENUM(
                "ACTIVE", "PROCESSING", "FAILED", "ARCHIVED", name="item_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("change_type", change_type, nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("change_summary", sa.Text()),
        sa.UniqueConstraint("item_id", "revision_number", name="uq_item_revisions_number"),
    )
    op.create_index("ix_item_revisions_item_id", "item_revisions", ["item_id"])
    op.create_index("ix_item_revisions_user_id", "item_revisions", ["user_id"])
    bind.execute(
        sa.text(
            "INSERT INTO item_revisions "
            "(id,item_id,user_id,revision_number,title_snapshot,content_snapshot,source_type_snapshot,"
            "source_url_snapshot,source_metadata_snapshot,effective_at_snapshot,status_snapshot,change_type) "
            "SELECT gen_random_uuid(),id,user_id,1,title,content,source_type,source_url,source_metadata,"
            "effective_at,status,'CREATED'::revision_change_type FROM items"
        )
    )


def downgrade():
    raise RuntimeError(
        "Migration 0003 is intentionally irreversible after status/revision data is written. "
        "Use a forward migration to change the vector or status schema without deleting audit history."
    )
