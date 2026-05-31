"""Minimal catch-up API schemas for Scroll Down Sports clients."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ....services.game_status import compute_status_flags
from .common import (
    LiveSnapshot,
    MLBBatterStat,
    MLBPitcherStat,
    NHLGoalieStat,
    NHLSkaterStat,
    PlayEntry,
    PlayerStat,
    ScoreObject,
    TeamStat,
)


class CatchupGameSummary(BaseModel):
    """Game list item without scoreboard data."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    league_code: str = Field(..., alias="leagueCode")
    game_date: datetime = Field(..., alias="gameDate")
    local_game_date: date | None = Field(None, alias="localGameDate")
    home_team: str = Field(..., alias="homeTeam")
    away_team: str = Field(..., alias="awayTeam")
    home_team_abbr: str | None = Field(None, alias="homeTeamAbbr")
    away_team_abbr: str | None = Field(None, alias="awayTeamAbbr")
    status: str | None = None
    current_period: int | None = Field(None, alias="currentPeriod")
    game_clock: str | None = Field(None, alias="gameClock")
    current_period_label: str | None = Field(None, alias="currentPeriodLabel")
    live_snapshot: LiveSnapshot | None = Field(None, alias="liveSnapshot")
    has_boxscore: bool = Field(False, alias="hasBoxscore")
    has_player_stats: bool = Field(False, alias="hasPlayerStats")
    has_pbp: bool = Field(False, alias="hasPbp")
    play_count: int = Field(0, alias="playCount")
    context: list[str] = Field(default_factory=list)
    context_source: str = Field("template", alias="contextSource")

    @computed_field(alias="isLive")  # type: ignore[misc]
    @property
    def is_live(self) -> bool:
        return compute_status_flags(self.status)["is_live"]

    @computed_field(alias="isFinal")  # type: ignore[misc]
    @property
    def is_final(self) -> bool:
        return compute_status_flags(self.status)["is_final"]

    @computed_field(alias="isPregame")  # type: ignore[misc]
    @property
    def is_pregame(self) -> bool:
        return compute_status_flags(self.status)["is_pregame"]


class CatchupGameListResponse(BaseModel):
    """Chronological catch-up game list."""

    model_config = ConfigDict(populate_by_name=True)

    games: list[CatchupGameSummary]
    total: int
    next_offset: int | None = Field(None, alias="nextOffset")
    with_boxscore_count: int = Field(0, alias="withBoxscoreCount")
    with_player_stats_count: int = Field(0, alias="withPlayerStatsCount")
    with_pbp_count: int = Field(0, alias="withPbpCount")


class CatchupGameMeta(CatchupGameSummary):
    """Game metadata for detail view; score is only returned after tap."""

    season: int
    season_type: str | None = Field(None, alias="seasonType")
    home_team_id: int | None = Field(None, alias="homeTeamId")
    away_team_id: int | None = Field(None, alias="awayTeamId")
    score: ScoreObject | None = None
    last_scraped_at: datetime | None = Field(None, alias="lastScrapedAt")
    last_ingested_at: datetime | None = Field(None, alias="lastIngestedAt")
    last_pbp_at: datetime | None = Field(None, alias="lastPbpAt")
    last_boxscore_at: datetime | None = Field(None, alias="lastBoxscoreAt")


class CatchupGameDetailResponse(BaseModel):
    """Straight catch-up detail: plays, players, teams, final score."""

    model_config = ConfigDict(populate_by_name=True)

    detail_contract_version: int = Field(2, alias="detailContractVersion")
    game: CatchupGameMeta
    plays: list[PlayEntry]
    player_stats: list[PlayerStat] = Field(default_factory=list, alias="playerStats")
    nhl_skaters: list[NHLSkaterStat] | None = Field(None, alias="nhlSkaters")
    nhl_goalies: list[NHLGoalieStat] | None = Field(None, alias="nhlGoalies")
    mlb_batters: list[MLBBatterStat] | None = Field(None, alias="mlbBatters")
    mlb_pitchers: list[MLBPitcherStat] | None = Field(None, alias="mlbPitchers")
    team_stats: list[TeamStat] = Field(default_factory=list, alias="teamStats")


class CatchupGameContextResponse(BaseModel):
    """Homepage context copy for a single game."""

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    context: list[str]
    source: str = "template"
