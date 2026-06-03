"""Sports boxscore and play event ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .base import Base

if TYPE_CHECKING:
    from .sports import SportsGame, SportsPlayer, SportsTeam


class SportsTeamBoxscore(Base):
    """Team-level boxscore data stored as JSONB for flexibility across sports."""

    __tablename__ = "sports_team_boxscores"

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
    stats: Mapped[dict[str, Any]] = mapped_column(
        "raw_stats_json", JSONB, server_default=text("'{}'::jsonb"), nullable=False
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

    game: Mapped[SportsGame] = relationship("SportsGame", back_populates="team_boxscores")
    team: Mapped[SportsTeam] = relationship("SportsTeam")

    __table_args__ = (UniqueConstraint("game_id", "team_id", name="uq_team_boxscore_game_team"),)


class SportsPlayerBoxscore(Base):
    """Player-level boxscores stored as JSONB for flexibility across sports."""

    __tablename__ = "sports_player_boxscores"

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
    stats: Mapped[dict[str, Any]] = mapped_column(
        "raw_stats_json", JSONB, server_default=text("'{}'::jsonb"), nullable=False
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

    game: Mapped[SportsGame] = relationship("SportsGame", back_populates="player_boxscores")
    team: Mapped[SportsTeam] = relationship("SportsTeam")

    __table_args__ = (
        UniqueConstraint(
            "game_id",
            "team_id",
            "player_external_ref",
            name="uq_player_boxscore_identity",
        ),
    )


class SportsGamePlay(Base):
    """Play-by-play events for games."""

    __tablename__ = "sports_game_plays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    game_clock: Mapped[str | None] = mapped_column(String(10), nullable=True)
    play_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Stable per-event identifier from the source feed (e.g., NHL eventId).
    # When present, this is the upsert identity instead of play_index, since
    # play_index = period * multiplier + sortOrder can drift across scrape runs.
    event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    play_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    team_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sports_teams.id", ondelete="SET NULL"), nullable=True
    )
    player_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    player_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    player_ref_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sports_players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    game: Mapped[SportsGame] = relationship("SportsGame", back_populates="plays")
    team: Mapped[SportsTeam | None] = relationship("SportsTeam", foreign_keys=[team_id])
    player_ref: Mapped[SportsPlayer | None] = relationship("SportsPlayer", back_populates="plays")

    __table_args__ = (
        Index("idx_game_plays_game", "game_id"),
        # Partial unique: play_index is only a stable identity for sources
        # without an event_id (NBA/MLB/NCAAB).  NHL plays carry event_id
        # and use the partial index below as their conflict target instead,
        # because play_index drifts with NHL sortOrder churn.
        Index(
            "uq_game_play_index",
            "game_id",
            "play_index",
            unique=True,
            postgresql_where=text("event_id IS NULL"),
        ),
        Index(
            "uq_sports_game_plays_game_event",
            "game_id",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
        ),
    )
