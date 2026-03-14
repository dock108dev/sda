"""Game-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import (
    LiveSnapshot,
    MLBBatterStat,
    MLBPitcherStat,
    NHLDataHealth,
    NHLGoalieStat,
    NHLSkaterStat,
    OddsEntry,
    PlayEntry,
    PlayerStat,
    SocialPostEntry,
    TeamStat,
    TieredPlayGroup,
)
from .mlb_advanced import (
    MLBAdvancedPlayerStats,
    MLBAdvancedTeamStats,
    MLBFieldingStatSchema,
    MLBPitcherGameStatSchema,
)


class GameSummary(BaseModel):
    """Game summary for list view with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    league_code: str = Field(..., alias="leagueCode")
    game_date: datetime = Field(..., alias="gameDate")
    home_team: str = Field(..., alias="homeTeam")
    away_team: str = Field(..., alias="awayTeam")
    status: str | None = None
    home_score: int | None = Field(None, alias="homeScore")
    away_score: int | None = Field(None, alias="awayScore")
    current_period: int | None = Field(None, alias="currentPeriod")
    game_clock: str | None = Field(None, alias="gameClock")
    has_boxscore: bool = Field(..., alias="hasBoxscore")
    has_player_stats: bool = Field(..., alias="hasPlayerStats")
    has_odds: bool = Field(..., alias="hasOdds")
    has_social: bool = Field(..., alias="hasSocial")
    has_pbp: bool = Field(..., alias="hasPbp")
    has_flow: bool = Field(..., alias="hasFlow")
    has_advanced_stats: bool = Field(False, alias="hasAdvancedStats")
    play_count: int = Field(..., alias="playCount")
    social_post_count: int = Field(..., alias="socialPostCount")
    scrape_version: int | None = Field(None, alias="scrapeVersion")
    last_scraped_at: datetime | None = Field(None, alias="lastScrapedAt")
    last_ingested_at: datetime | None = Field(None, alias="lastIngestedAt")
    last_pbp_at: datetime | None = Field(None, alias="lastPbpAt")
    last_social_at: datetime | None = Field(None, alias="lastSocialAt")
    last_odds_at: datetime | None = Field(None, alias="lastOddsAt")
    last_advanced_stats_at: datetime | None = Field(None, alias="lastAdvancedStatsAt")
    derived_metrics: dict[str, Any] | None = Field(None, alias="derivedMetrics")
    home_team_abbr: str | None = Field(None, alias="homeTeamAbbr")
    away_team_abbr: str | None = Field(None, alias="awayTeamAbbr")
    home_team_color_light: str | None = Field(None, alias="homeTeamColorLight")
    home_team_color_dark: str | None = Field(None, alias="homeTeamColorDark")
    away_team_color_light: str | None = Field(None, alias="awayTeamColorLight")
    away_team_color_dark: str | None = Field(None, alias="awayTeamColorDark")
    is_live: bool | None = Field(None, alias="isLive")
    is_final: bool | None = Field(None, alias="isFinal")
    is_pregame: bool | None = Field(None, alias="isPregame")
    is_truly_completed: bool | None = Field(None, alias="isTrulyCompleted")
    read_eligible: bool | None = Field(None, alias="readEligible")
    current_period_label: str | None = Field(None, alias="currentPeriodLabel")
    live_snapshot: LiveSnapshot | None = Field(None, alias="liveSnapshot")
    date_section: str | None = Field(None, alias="dateSection")


class GameListResponse(BaseModel):
    """Game list response with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    games: list[GameSummary]
    total: int
    next_offset: int | None = Field(None, alias="nextOffset")
    with_boxscore_count: int | None = Field(0, alias="withBoxscoreCount")
    with_player_stats_count: int | None = Field(0, alias="withPlayerStatsCount")
    with_odds_count: int | None = Field(0, alias="withOddsCount")
    with_social_count: int | None = Field(0, alias="withSocialCount")
    with_pbp_count: int | None = Field(0, alias="withPbpCount")
    with_flow_count: int | None = Field(0, alias="withFlowCount")
    with_advanced_stats_count: int | None = Field(0, alias="withAdvancedStatsCount")


class GameMeta(BaseModel):
    """Game metadata with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    league_code: str = Field(..., alias="leagueCode")
    season: int
    season_type: str | None = Field(None, alias="seasonType")
    game_date: datetime = Field(..., alias="gameDate")
    home_team: str = Field(..., alias="homeTeam")
    away_team: str = Field(..., alias="awayTeam")
    home_team_id: int | None = Field(None, alias="homeTeamId")
    away_team_id: int | None = Field(None, alias="awayTeamId")
    home_score: int | None = Field(None, alias="homeScore")
    away_score: int | None = Field(None, alias="awayScore")
    status: str
    scrape_version: int | None = Field(None, alias="scrapeVersion")
    last_scraped_at: datetime | None = Field(None, alias="lastScrapedAt")
    last_ingested_at: datetime | None = Field(None, alias="lastIngestedAt")
    last_pbp_at: datetime | None = Field(None, alias="lastPbpAt")
    last_social_at: datetime | None = Field(None, alias="lastSocialAt")
    last_odds_at: datetime | None = Field(None, alias="lastOddsAt")
    last_advanced_stats_at: datetime | None = Field(None, alias="lastAdvancedStatsAt")
    has_boxscore: bool = Field(..., alias="hasBoxscore")
    has_player_stats: bool = Field(..., alias="hasPlayerStats")
    has_odds: bool = Field(..., alias="hasOdds")
    has_social: bool = Field(..., alias="hasSocial")
    has_pbp: bool = Field(..., alias="hasPbp")
    has_flow: bool = Field(..., alias="hasFlow")
    has_advanced_stats: bool = Field(False, alias="hasAdvancedStats")
    play_count: int = Field(..., alias="playCount")
    social_post_count: int = Field(..., alias="socialPostCount")
    home_team_x_handle: str | None = Field(None, alias="homeTeamXHandle")
    away_team_x_handle: str | None = Field(None, alias="awayTeamXHandle")
    home_team_abbr: str | None = Field(None, alias="homeTeamAbbr")
    away_team_abbr: str | None = Field(None, alias="awayTeamAbbr")
    home_team_color_light: str | None = Field(None, alias="homeTeamColorLight")
    home_team_color_dark: str | None = Field(None, alias="homeTeamColorDark")
    away_team_color_light: str | None = Field(None, alias="awayTeamColorLight")
    away_team_color_dark: str | None = Field(None, alias="awayTeamColorDark")
    is_live: bool | None = Field(None, alias="isLive")
    is_final: bool | None = Field(None, alias="isFinal")
    is_pregame: bool | None = Field(None, alias="isPregame")
    is_truly_completed: bool | None = Field(None, alias="isTrulyCompleted")
    read_eligible: bool | None = Field(None, alias="readEligible")
    current_period_label: str | None = Field(None, alias="currentPeriodLabel")
    live_snapshot: LiveSnapshot | None = Field(None, alias="liveSnapshot")


class GameDetailResponse(BaseModel):
    """Game detail response with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    game: GameMeta
    team_stats: list[TeamStat] = Field(..., alias="teamStats")
    # Generic player stats (NBA, NCAAB, NFL, etc.)
    player_stats: list[PlayerStat] = Field(..., alias="playerStats")
    # NHL-specific player stats (only populated for NHL games)
    nhl_skaters: list[NHLSkaterStat] | None = Field(None, alias="nhlSkaters")
    nhl_goalies: list[NHLGoalieStat] | None = Field(None, alias="nhlGoalies")
    # MLB-specific player stats (only populated for MLB games)
    mlb_batters: list[MLBBatterStat] | None = Field(None, alias="mlbBatters")
    mlb_pitchers: list[MLBPitcherStat] | None = Field(None, alias="mlbPitchers")
    # MLB advanced stats (Statcast-derived, only populated for MLB games)
    mlb_advanced_stats: list[MLBAdvancedTeamStats] | None = Field(None, alias="mlbAdvancedStats")
    mlb_advanced_player_stats: list[MLBAdvancedPlayerStats] | None = Field(
        None, alias="mlbAdvancedPlayerStats"
    )
    mlb_pitcher_game_stats: list[MLBPitcherGameStatSchema] | None = Field(
        None, alias="mlbPitcherGameStats"
    )
    mlb_fielding_stats: list[MLBFieldingStatSchema] | None = Field(
        None, alias="mlbFieldingStats"
    )
    odds: list[OddsEntry]
    social_posts: list[SocialPostEntry] = Field(..., alias="socialPosts")
    plays: list[PlayEntry]
    grouped_plays: list[TieredPlayGroup] | None = Field(None, alias="groupedPlays")
    derived_metrics: dict[str, Any] = Field(..., alias="derivedMetrics")
    raw_payloads: dict[str, Any] = Field(..., alias="rawPayloads")
    # NHL-specific data health (only populated for NHL games)
    data_health: NHLDataHealth | None = Field(None, alias="dataHealth")
    odds_table: list[dict[str, Any]] | None = Field(None, alias="oddsTable")
    stat_annotations: list[dict[str, Any]] | None = Field(None, alias="statAnnotations")


class GamePreviewScoreResponse(BaseModel):
    """Game preview score with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    game_id: str = Field(..., alias="gameId")
    excitement_score: int = Field(..., alias="excitementScore")
    quality_score: int = Field(..., alias="qualityScore")
    tags: list[str]
    nugget: str


class JobResponse(BaseModel):
    """Job response with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: int = Field(..., alias="runId")
    job_id: str | None = Field(None, alias="jobId")
    message: str
