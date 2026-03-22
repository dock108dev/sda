"""NFL advanced game stats (nflverse EPA/WPA/CPOE-derived, post-game).

Contains team-level and player-level advanced stats computed from
nflverse play-by-play data: EPA, WPA, CPOE, success rates, and
explosive play rates.
"""

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


class NFLGameAdvancedStats(Base):
    """Team-level advanced stats for an NFL game.

    Derived from nflverse play-by-play data with pre-computed EPA, WPA,
    and CPOE. Two rows per game (home + away). Computed post-game only.
    """

    __tablename__ = "nfl_game_advanced_stats"

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

    # EPA metrics
    total_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    rush_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    epa_per_play: Mapped[float | None] = mapped_column(Float, nullable=True)

    # WPA
    total_wpa: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Success rates
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    rush_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Explosive plays
    explosive_play_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Passing context
    avg_cpoe: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_air_yards: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_yac: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Volume
    total_plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pass_plays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rush_plays: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    game = relationship("SportsGame", back_populates="nfl_advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_nfl_advanced_game_team"),
        Index("idx_nfl_advanced_game", "game_id"),
        Index("idx_nfl_advanced_team", "team_id"),
    )


class NFLPlayerAdvancedStats(Base):
    """Player-level advanced stats for an NFL game.

    One row per player per role (passer/rusher/receiver) per game.
    Derived from nflverse play-by-play EPA/WPA/CPOE data.
    """

    __tablename__ = "nfl_player_advanced_stats"

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
    player_external_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    player_name: Mapped[str] = mapped_column(String(200), nullable=False)
    player_role: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # EPA
    total_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    epa_per_play: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Role-specific EPA
    pass_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    rush_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    receiving_epa: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Passing
    cpoe: Mapped[float | None] = mapped_column(Float, nullable=True)
    air_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    yac_epa: Mapped[float | None] = mapped_column(Float, nullable=True)
    air_yards: Mapped[float | None] = mapped_column(Float, nullable=True)

    # WPA
    total_wpa: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Success
    success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Volume
    plays: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    game = relationship("SportsGame", back_populates="nfl_player_advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "game_id", "team_id", "player_external_ref", "player_role",
            name="uq_nfl_player_advanced_game_team_player_role",
        ),
        Index("idx_nfl_player_advanced_game", "game_id"),
        Index("idx_nfl_player_advanced_team", "team_id"),
    )
