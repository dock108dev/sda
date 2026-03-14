"""Core sports models: leagues, teams, players, games, boxscores, plays."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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
    from .flow import SportsGameTimelineArtifact
    from .mlb_advanced import MLBGameAdvancedStats, MLBPitcherGameStats, MLBPlayerAdvancedStats
    from .odds import SportsGameOdds
    from .scraper import SportsScrapeRun
    from .social import TeamSocialAccount, TeamSocialPost


class GameStatus(str, Enum):
    """Canonical game status lifecycle.

    Happy path: scheduled → pregame → live → final → archived
    """

    scheduled = "scheduled"
    pregame = "pregame"  # Within pregame_window_hours of game_date
    live = "live"
    final = "final"
    archived = "archived"  # Data complete, flows generated, >7 days old
    postponed = "postponed"
    canceled = "canceled"


class SportsLeague(Base):
    """Sports leagues (NFL, NCAAF, NBA, NCAAB, MLB, NHL)."""

    __tablename__ = "sports_leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    teams: Mapped[list[SportsTeam]] = relationship(
        "SportsTeam", back_populates="league", cascade="all, delete-orphan"
    )
    games: Mapped[list[SportsGame]] = relationship(
        "SportsGame", back_populates="league", cascade="all, delete-orphan"
    )
    scrape_runs: Mapped[list[SportsScrapeRun]] = relationship(
        "SportsScrapeRun", back_populates="league"
    )


class SportsTeam(Base):
    """Sports teams with external provider mappings."""

    __tablename__ = "sports_teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(100), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color_light_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_dark_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    x_handle: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    external_codes: Mapped[dict[str, Any]] = mapped_column(
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

    league: Mapped[SportsLeague] = relationship("SportsLeague", back_populates="teams")
    home_games: Mapped[list[SportsGame]] = relationship(
        "SportsGame",
        foreign_keys="[SportsGame.home_team_id]",
        back_populates="home_team",
    )
    away_games: Mapped[list[SportsGame]] = relationship(
        "SportsGame",
        foreign_keys="[SportsGame.away_team_id]",
        back_populates="away_team",
    )
    social_accounts: Mapped[list[TeamSocialAccount]] = relationship(
        "TeamSocialAccount", back_populates="team", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_sports_teams_league_name", "league_id", "name", unique=True),
        Index("idx_sports_teams_league_name_lower", "league_id", text("lower(name)")),
    )


class SportsPlayer(Base):
    """Master player records linked to PBP and boxscores."""

    __tablename__ = "sports_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_leagues.id"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sweater_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id"),
        nullable=True,
        index=True,
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

    league: Mapped[SportsLeague] = relationship("SportsLeague")
    team: Mapped[SportsTeam | None] = relationship("SportsTeam")
    plays: Mapped[list[SportsGamePlay]] = relationship(
        "SportsGamePlay", back_populates="player_ref"
    )

    __table_args__ = (
        Index("idx_players_external_id", "external_id"),
        Index("idx_players_name", "name"),
        Index("uq_player_identity", "league_id", "external_id", unique=True),
    )


class SportsGame(Base):
    """Individual games with unique constraints to prevent duplicates."""

    __tablename__ = "sports_games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_leagues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    season_type: Mapped[str] = mapped_column(String(50), nullable=False)
    game_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    home_team_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    away_team_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sports_teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=GameStatus.scheduled, nullable=False, index=True
    )
    source_game_key: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    scrape_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_pbp_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_boxscore_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_social_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_odds_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_advanced_stats_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    social_scrape_1_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    social_scrape_2_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    league: Mapped[SportsLeague] = relationship("SportsLeague", back_populates="games")
    home_team: Mapped[SportsTeam] = relationship(
        "SportsTeam", foreign_keys=[home_team_id], back_populates="home_games"
    )
    away_team: Mapped[SportsTeam] = relationship(
        "SportsTeam", foreign_keys=[away_team_id], back_populates="away_games"
    )
    team_boxscores: Mapped[list[SportsTeamBoxscore]] = relationship(
        "SportsTeamBoxscore", back_populates="game", cascade="all, delete-orphan"
    )
    player_boxscores: Mapped[list[SportsPlayerBoxscore]] = relationship(
        "SportsPlayerBoxscore", back_populates="game", cascade="all, delete-orphan"
    )
    odds: Mapped[list[SportsGameOdds]] = relationship(
        "SportsGameOdds", back_populates="game", cascade="all, delete-orphan"
    )
    social_posts: Mapped[list[TeamSocialPost]] = relationship(
        "TeamSocialPost",
        primaryjoin="and_(SportsGame.id == TeamSocialPost.game_id, TeamSocialPost.mapping_status == 'mapped')",
        foreign_keys="[TeamSocialPost.game_id]",
        viewonly=True,
        lazy="select",
    )
    plays: Mapped[list[SportsGamePlay]] = relationship(
        "SportsGamePlay", back_populates="game", cascade="all, delete-orphan"
    )
    timeline_artifacts: Mapped[list[SportsGameTimelineArtifact]] = relationship(
        "SportsGameTimelineArtifact",
        back_populates="game",
        cascade="all, delete-orphan",
    )
    advanced_stats: Mapped[list[MLBGameAdvancedStats]] = relationship(
        "MLBGameAdvancedStats",
        back_populates="game",
        cascade="all, delete-orphan",
    )
    player_advanced_stats: Mapped[list[MLBPlayerAdvancedStats]] = relationship(
        "MLBPlayerAdvancedStats",
        back_populates="game",
        cascade="all, delete-orphan",
    )
    pitcher_game_stats: Mapped[list[MLBPitcherGameStats]] = relationship(
        "MLBPitcherGameStats",
        back_populates="game",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "league_id",
            "season",
            "game_date",
            "home_team_id",
            "away_team_id",
            name="uq_game_identity",
        ),
        Index("idx_games_league_season_date", "league_id", "season", "game_date"),
        Index("idx_games_teams", "home_team_id", "away_team_id"),
        Index("idx_games_league_status", "league_id", "status"),
    )

    @property
    def is_final(self) -> bool:
        """Check if game is in a final state."""
        return self.status == GameStatus.final.value

    @property
    def is_archived(self) -> bool:
        """Check if game has been archived (terminal state)."""
        return self.status == GameStatus.archived.value

    @property
    def is_active(self) -> bool:
        """Check if game is in an active lifecycle state (not terminal)."""
        return self.status in (
            GameStatus.scheduled.value,
            GameStatus.pregame.value,
            GameStatus.live.value,
            GameStatus.final.value,
        )



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
    play_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    team_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sports_teams.id"), nullable=True
    )
    player_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    player_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    player_ref_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sports_players.id"),
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
        UniqueConstraint("game_id", "play_index", name="uq_game_play_index"),
    )
