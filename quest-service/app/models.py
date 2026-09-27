from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(255))
    # kill_monster / collect_item / win_dungeon / reach_level
    type: Mapped[str] = mapped_column(String(20))
    # dungeon-service의 monster/item/dungeon id (다른 서비스 DB이므로 FK 없음). reach_level은 None
    target_id: Mapped[int | None]
    target_count: Mapped[int]
    min_level: Mapped[int]
    reward_exp: Mapped[int]


class QuestProgress(Base):
    __tablename__ = "quest_progress"
    __table_args__ = (UniqueConstraint("character_id", "quest_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # character-service의 characters.id (FK 없음)
    character_id: Mapped[int] = mapped_column(index=True)
    # 수락 시점의 소유자. 조회할 때마다 character-service를 호출하지 않으려고 저장해 둔다
    user_id: Mapped[int]
    quest_id: Mapped[int] = mapped_column(ForeignKey("quests.id"))
    status: Mapped[str] = mapped_column(String(20))  # in_progress / completed
    progress: Mapped[int]
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """이미 처리한 이벤트 기록 (중복 소비 방지용)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
