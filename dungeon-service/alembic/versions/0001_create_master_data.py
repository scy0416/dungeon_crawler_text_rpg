"""create master data tables and seed

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
    dungeons = op.create_table(
        "dungeons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    monsters = op.create_table(
        "monsters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dungeon_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("hp", sa.Integer(), nullable=False),
        sa.Column("atk", sa.Integer(), nullable=False),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("exp_reward", sa.Integer(), nullable=False),
        sa.Column("spawn_weight", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["dungeon_id"], ["dungeons.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_monsters_dungeon_id"), "monsters", ["dungeon_id"], unique=False)
    items = op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    monster_drops = op.create_table(
        "monster_drops",
        sa.Column("monster_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("drop_rate", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["monster_id"], ["monsters.id"]),
        sa.PrimaryKeyConstraint("monster_id", "item_id"),
    )

    # 초기 마스터 데이터
    op.bulk_insert(dungeons, [
        {"id": 1, "name": "고블린 동굴", "description": "초보 모험가를 위한 축축한 동굴", "min_level": 1},
        {"id": 2, "name": "버려진 요새", "description": "언데드와 오크가 점거한 옛 요새", "min_level": 3},
    ])
    op.bulk_insert(monsters, [
        {"id": 1, "dungeon_id": 1, "name": "슬라임", "hp": 30, "atk": 8, "defense": 2, "exp_reward": 15, "spawn_weight": 50},
        {"id": 2, "dungeon_id": 1, "name": "고블린", "hp": 45, "atk": 12, "defense": 4, "exp_reward": 25, "spawn_weight": 35},
        {"id": 3, "dungeon_id": 1, "name": "고블린 주술사", "hp": 35, "atk": 15, "defense": 3, "exp_reward": 30, "spawn_weight": 15},
        {"id": 4, "dungeon_id": 2, "name": "스켈레톤", "hp": 70, "atk": 18, "defense": 8, "exp_reward": 50, "spawn_weight": 60},
        {"id": 5, "dungeon_id": 2, "name": "오크 전사", "hp": 100, "atk": 22, "defense": 10, "exp_reward": 80, "spawn_weight": 40},
    ])
    op.bulk_insert(items, [
        {"id": 1, "name": "슬라임 젤리", "description": "끈적끈적한 젤리"},
        {"id": 2, "name": "녹슨 단검", "description": "고블린이 쓰던 낡은 단검"},
        {"id": 3, "name": "고블린 부적", "description": "희미한 마력이 느껴지는 부적"},
        {"id": 4, "name": "뼛조각", "description": "스켈레톤의 뼈 일부"},
        {"id": 5, "name": "오크 이빨", "description": "전리품으로 인기 있는 큰 이빨"},
    ])
    op.bulk_insert(monster_drops, [
        {"monster_id": 1, "item_id": 1, "drop_rate": 0.6},
        {"monster_id": 2, "item_id": 2, "drop_rate": 0.3},
        {"monster_id": 3, "item_id": 3, "drop_rate": 0.4},
        {"monster_id": 4, "item_id": 4, "drop_rate": 0.5},
        {"monster_id": 5, "item_id": 5, "drop_rate": 0.4},
        {"monster_id": 5, "item_id": 2, "drop_rate": 0.2},
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("monster_drops")
    op.drop_table("items")
    op.drop_index(op.f("ix_monsters_dungeon_id"), table_name="monsters")
    op.drop_table("monsters")
    op.drop_table("dungeons")
