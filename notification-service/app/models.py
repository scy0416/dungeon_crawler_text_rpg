from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    # character-service의 characters.id (FK 없음)
    character_id: Mapped[int] = mapped_column(index=True)
    type: Mapped[str] = mapped_column(String(30))  # quest_completed / level_up
    message: Mapped[str] = mapped_column(String(255))
    # 알림을 만든 이벤트 (추적용)
    source_event_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """이미 처리한 이벤트 기록 (중복 소비 방지용)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
