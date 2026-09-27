"""create quests, quest progress, processed events and seed quests

Revision ID: 0001
Revises:
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    quests = op.create_table(
        "quests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.Column("reward_exp", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "quest_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quest_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["quest_id"], ["quests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("character_id", "quest_id"),
    )
    op.create_index(
        op.f("ix_quest_progress_character_id"), "quest_progress", ["character_id"], unique=False
    )
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

    # 초기 퀘스트 (target_id는 dungeon-service 시드 데이터의 id)
    op.bulk_insert(quests, [
        {"id": 1, "name": "슬라임 퇴치", "description": "슬라임 3마리를 처치하라",
         "type": "kill_monster", "target_id": 1, "target_count": 3, "min_level": 1, "reward_exp": 50},
        {"id": 2, "name": "고블린 소탕", "description": "고블린 5마리를 처치하라",
         "type": "kill_monster", "target_id": 2, "target_count": 5, "min_level": 1, "reward_exp": 100},
        {"id": 3, "name": "젤리 수집가", "description": "슬라임 젤리 3개를 모아라",
         "type": "collect_item", "target_id": 1, "target_count": 3, "min_level": 1, "reward_exp": 60},
        {"id": 4, "name": "동굴 탐험가", "description": "고블린 동굴에서 10번 승리하라",
         "type": "win_dungeon", "target_id": 1, "target_count": 10, "min_level": 1, "reward_exp": 150},
        {"id": 5, "name": "성장의 증거", "description": "레벨 3에 도달하라",
         "type": "reach_level", "target_id": None, "target_count": 3, "min_level": 1, "reward_exp": 100},
        {"id": 6, "name": "요새 정복자", "description": "버려진 요새에서 5번 승리하라",
         "type": "win_dungeon", "target_id": 2, "target_count": 5, "min_level": 3, "reward_exp": 300},
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("processed_events")
    op.drop_index(op.f("ix_quest_progress_character_id"), table_name="quest_progress")
    op.drop_table("quest_progress")
    op.drop_table("quests")
