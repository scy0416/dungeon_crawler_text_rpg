"""add outbox

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("stream", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(op.f("ix_outbox_published_at"), "outbox", ["published_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_outbox_published_at"), table_name="outbox")
    op.drop_table("outbox")
