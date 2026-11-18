"""Add optional users.display_name (additive, nullable, no data rewrite)."""

import sqlalchemy as sa

from alembic import op

revision = "0004_user_display_name"
down_revision = "0003_models_history_status_ist"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("display_name", sa.String(length=80), nullable=True))


def downgrade():
    op.drop_column("users", "display_name")
