from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Dungeon(Base):
    __tablename__ = "dungeons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(255))
    min_level: Mapped[int]


class Monster(Base):
    __tablename__ = "monsters"

    id: Mapped[int] = mapped_column(primary_key=True)
    dungeon_id: Mapped[int] = mapped_column(ForeignKey("dungeons.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    hp: Mapped[int]
    atk: Mapped[int]
    defense: Mapped[int]
    exp_reward: Mapped[int]
    spawn_weight: Mapped[int]


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(255))


class MonsterDrop(Base):
    __tablename__ = "monster_drops"

    monster_id: Mapped[int] = mapped_column(ForeignKey("monsters.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    drop_rate: Mapped[float] = mapped_column(Float)
