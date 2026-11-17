"""Add user ownership, temporal metadata, and persistent conversations."""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

revision = "0002_users_temporal_chat"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("items", sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("items", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))

    unowned_count = bind.execute(sa.text("SELECT count(*) FROM items")).scalar_one()
    owner_id = None
    if unowned_count:
        settings = get_settings()
        if not settings.migration_owner_email or not settings.migration_owner_password_hash:
            raise RuntimeError(
                "Existing items have no owner. Set MIGRATION_OWNER_EMAIL and MIGRATION_OWNER_PASSWORD_HASH "
                "(a scrypt hash) to preserve them under an explicitly configured bootstrap owner, then retry."
            )
        owner_id = uuid.uuid4()
        bind.execute(
            sa.text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :password_hash)"),
            {
                "id": owner_id,
                "email": settings.migration_owner_email.strip().lower(),
                "password_hash": settings.migration_owner_password_hash,
            },
        )
        bind.execute(sa.text("UPDATE items SET user_id = :owner_id"), {"owner_id": owner_id})
    if owner_id is not None:
        bind.execute(
            sa.text("UPDATE items SET user_id = :owner_id WHERE user_id IS NULL"), {"owner_id": owner_id}
        )
    elif unowned_count == 0:
        # Empty installations can safely adopt the non-null ownership constraint immediately.
        pass
    op.create_foreign_key("fk_items_user_id_users", "items", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_items_user_id", "items", ["user_id"])
    op.alter_column("items", "user_id", nullable=False)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    role = sa.Enum("user", "assistant", name="message_role")
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])


def downgrade():
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_index("ix_items_user_id", table_name="items")
    op.drop_constraint("fk_items_user_id_users", "items", type_="foreignkey")
    op.drop_column("items", "user_id")
    op.drop_column("items", "effective_at")
    op.drop_table("users")
    sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=True)
