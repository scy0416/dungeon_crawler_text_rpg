"""add max stats, inventory, processed events

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27

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
    # 기존 캐릭터는 초기 스탯 기준 최대치로 채운다
    op.add_column("characters", sa.Column("max_hp", sa.Integer(), server_default="100", nullable=False))
    op.add_column("characters", sa.Column("max_mp", sa.Integer(), server_default="50", nullable=False))
    op.create_table(
        "inventory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id", "item_id"),
    )
    op.create_index(op.f("ix_inventory_character_id"), "inventory", ["character_id"], unique=False)
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("processed_events")
    op.drop_index(op.f("ix_inventory_character_id"), table_name="inventory")
    op.drop_table("inventory")
    op.drop_column("characters", "max_mp")
    op.drop_column("characters", "max_hp")
