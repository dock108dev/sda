"""MLB advanced game stats (Statcast-derived, post-game)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .base import Base


class MLBGameAdvancedStats(Base):
    """Team-level advanced batting stats for an MLB game.

    Derived from pitch-level Statcast data in the MLB Stats API playByPlay
    endpoint. Computed post-game only (deterministic, never live).

    Two categories:
    - Plate discipline: zone swing/contact rates
    - Quality of contact: exit velocity, hard-hit rate, barrel rate
    """

    __tablename__ = "mlb_game_advanced_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Plate discipline — raw counts
    total_pitches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone_pitches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone_swings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone_contact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outside_pitches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outside_swings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outside_contact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Plate discipline — derived percentages
    z_swing_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    o_swing_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_contact_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    o_contact_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Quality of contact — raw counts
    balls_in_play: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_exit_velo: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hard_hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    barrel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Quality of contact — derived percentages
    avg_exit_velo: Mapped[float | None] = mapped_column(Float, nullable=True)
    hard_hit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    barrel_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Extensibility
    raw_extras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    game = relationship("SportsGame", back_populates="advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_mlb_advanced_game_team"),
        Index("idx_mlb_advanced_game", "game_id"),
        Index("idx_mlb_advanced_team", "team_id"),
    )
