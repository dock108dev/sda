"""NHL advanced game stats (MoneyPuck xGoals-derived, post-game).

Contains team-level, skater-level, and goalie-level advanced stats
derived from MoneyPuck's expected goals model applied to every shot.
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


class NHLGameAdvancedStats(Base):
    """Team-level advanced stats for an NHL game.

    Derived from MoneyPuck shot-level CSV data with pre-computed xGoal
    probabilities. Computed post-game only (deterministic, never live).

    Two rows per game (home + away). Covers:
    - Shot quality (xGoals model)
    - Possession metrics (Corsi, Fenwick)
    - Shooting efficiency and PDO
    - Danger zone analysis
    """

    __tablename__ = "nhl_game_advanced_stats"

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

    # Shot quality (from MoneyPuck xG model)
    xgoals_for: Mapped[float | None] = mapped_column(Float, nullable=True)
    xgoals_against: Mapped[float | None] = mapped_column(Float, nullable=True)
    xgoals_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Possession metrics (from shot attempts)
    corsi_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corsi_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corsi_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    fenwick_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fenwick_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fenwick_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Shooting
    shots_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shooting_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    save_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pdo: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Danger zones
    high_danger_shots_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_danger_goals_for: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_danger_shots_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_danger_goals_against: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    game = relationship("SportsGame", back_populates="nhl_advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint("game_id", "team_id", name="uq_nhl_advanced_game_team"),
        Index("idx_nhl_advanced_game", "game_id"),
        Index("idx_nhl_advanced_team", "team_id"),
    )


class NHLSkaterAdvancedStats(Base):
    """Skater-level advanced stats for an NHL game.

    Per-skater aggregations from MoneyPuck shot data including
    xGoals, shooting, per-60 rates, and game score.
    """

    __tablename__ = "nhl_skater_advanced_stats"

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

    # Time on ice (decimal minutes, e.g. 18.45)
    toi_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)

    # xGoals
    xgoals_for: Mapped[float | None] = mapped_column(Float, nullable=True)
    xgoals_against: Mapped[float | None] = mapped_column(Float, nullable=True)
    on_ice_xgoals_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Shots
    shots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shooting_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Per-60 rates
    goals_per_60: Mapped[float | None] = mapped_column(Float, nullable=True)
    assists_per_60: Mapped[float | None] = mapped_column(Float, nullable=True)
    points_per_60: Mapped[float | None] = mapped_column(Float, nullable=True)
    shots_per_60: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Impact
    game_score: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    game = relationship("SportsGame", back_populates="nhl_skater_advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "game_id", "team_id", "player_external_ref",
            name="uq_nhl_skater_advanced_game_team_player",
        ),
        Index("idx_nhl_skater_advanced_game", "game_id"),
        Index("idx_nhl_skater_advanced_team", "team_id"),
    )


class NHLGoalieAdvancedStats(Base):
    """Goalie-level advanced stats for an NHL game.

    Per-goalie aggregations from MoneyPuck shot data including
    xGoals against, goals saved above expected, and danger-zone save rates.
    """

    __tablename__ = "nhl_goalie_advanced_stats"

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

    # Core
    xgoals_against: Mapped[float | None] = mapped_column(Float, nullable=True)
    goals_against: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goals_saved_above_expected: Mapped[float | None] = mapped_column(Float, nullable=True)
    save_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Danger zone saves
    high_danger_save_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    medium_danger_save_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_danger_save_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    shots_against: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    game = relationship("SportsGame", back_populates="nhl_goalie_advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "game_id", "player_external_ref",
            name="uq_nhl_goalie_advanced_game_player",
        ),
        Index("idx_nhl_goalie_advanced_game", "game_id"),
        Index("idx_nhl_goalie_advanced_player", "player_external_ref"),
    )
