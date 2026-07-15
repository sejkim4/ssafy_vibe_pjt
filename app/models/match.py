from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.location import Location


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    filters: Mapped[list["MatchFilter"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )
    games: Mapped[list["MatchGame"]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
    )


class MatchFilter(Base):
    __tablename__ = "match_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    filter_type: Mapped[str] = mapped_column(String, nullable=False)
    filter_value: Mapped[str] = mapped_column(String, nullable=False)
    is_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    match: Mapped["Match"] = relationship(back_populates="filters")


class MatchGame(Base):
    __tablename__ = "match_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    order_in_round: Mapped[int] = mapped_column(Integer, nullable=False)
    location_a_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    location_b_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    winner_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    match: Mapped["Match"] = relationship(back_populates="games")
    location_a: Mapped["Location"] = relationship(foreign_keys=[location_a_id])
    location_b: Mapped["Location"] = relationship(foreign_keys=[location_b_id])
    winner: Mapped["Location | None"] = relationship(foreign_keys=[winner_id])
