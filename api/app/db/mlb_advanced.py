"""MLB advanced game stats (Statcast-derived, post-game).

Contains team-level and player-level advanced batting stats,
pitcher game stats, and player fielding stats.
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


class MLBPlayerAdvancedStats(Base):
    """Player-level advanced batting stats for an MLB game.

    Same stat columns as MLBGameAdvancedStats, plus player identification.
    """

    __tablename__ = "mlb_player_advanced_stats"

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
    game = relationship("SportsGame", back_populates="player_advanced_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "game_id", "team_id", "player_external_ref",
            name="uq_mlb_player_advanced_game_team_player",
        ),
        Index("idx_mlb_player_advanced_game", "game_id"),
        Index("idx_mlb_player_advanced_team", "team_id"),
    )


class MLBPitcherGameStats(Base):
    """Per-pitcher per-game stats derived from boxscores and Statcast PBP.

    Stores both the standard pitching line (IP, K, BB, HR, etc.) and
    Statcast-derived aggregates from the pitcher's perspective (batters
    faced, zone/outside splits, exit velo against, barrel against).
    """

    __tablename__ = "mlb_pitcher_game_stats"

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
    player_external_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    player_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_starter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Standard pitching line
    innings_pitched: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    earned_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    walks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strikeouts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    home_runs_allowed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pitches_thrown: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strikes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Statcast aggregates from pitcher perspective
    batters_faced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone_pitches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone_swings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone_contact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outside_pitches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outside_swings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outside_contact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balls_in_play: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_exit_velo_against: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hard_hit_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    barrel_against: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Derived rates (computed at ingestion time)
    k_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    bb_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    whiff_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_contact_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    chase_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_exit_velo_against: Mapped[float | None] = mapped_column(Float, nullable=True)
    hard_hit_pct_against: Mapped[float | None] = mapped_column(Float, nullable=True)
    barrel_pct_against: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Extensibility
    raw_extras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    game = relationship("SportsGame", back_populates="pitcher_game_stats")
    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "game_id", "team_id", "player_external_ref",
            name="uq_mlb_pitcher_game_stats_identity",
        ),
        Index("idx_pitcher_game_stats_game", "game_id"),
        Index("idx_pitcher_game_stats_player", "player_external_ref"),
    )


class MLBPlayerFieldingStats(Base):
    """Player-level fielding stats (season or rolling window).

    Stores advanced defensive metrics sourced from Baseball Savant or
    derived from boxscore data. Supports both season-level aggregates
    (OAA, DRS, UZR from Savant) and game-level basics (errors, assists,
    putouts from boxscores).

    The system degrades gracefully when fielding data is missing — it is
    optional for training and simulation.
    """

    __tablename__ = "mlb_player_fielding_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_external_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    player_name: Mapped[str] = mapped_column(String(200), nullable=False)
    team_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Advanced metrics (from Baseball Savant — nullable when unavailable)
    outs_above_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    defensive_runs_saved: Mapped[float | None] = mapped_column(Float, nullable=True)
    uzr: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Basic metrics (from boxscores — more commonly available)
    games_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    innings_at_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assists: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    putouts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Composite defensive value (derived or provided)
    defensive_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_extras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    team = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "player_external_ref", "season", "position",
            name="uq_mlb_fielding_player_season_pos",
        ),
        Index("idx_fielding_player", "player_external_ref"),
        Index("idx_fielding_team_season", "team_id", "season"),
    )
