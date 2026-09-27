from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True)
    # auth-service의 users.id. 다른 서비스 DB이므로 FK를 걸지 않는다.
    user_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(20), unique=True)
    level: Mapped[int] = mapped_column(default=1)
    exp: Mapped[int] = mapped_column(default=0)
    hp: Mapped[int] = mapped_column(default=100)
    max_hp: Mapped[int] = mapped_column(default=100)
    mp: Mapped[int] = mapped_column(default=50)
    max_mp: Mapped[int] = mapped_column(default=50)
    atk: Mapped[int] = mapped_column(default=10)
    defense: Mapped[int] = mapped_column(default=5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class InventoryItem(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("character_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    # dungeon-service의 items.id. 다른 서비스 DB이므로 FK를 걸지 않는다.
    item_id: Mapped[int]
    quantity: Mapped[int] = mapped_column(default=0)


class ProcessedEvent(Base):
    """이미 처리한 이벤트 기록 (중복 소비 방지용)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
