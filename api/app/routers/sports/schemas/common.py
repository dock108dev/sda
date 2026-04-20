"""Shared stat models and common types."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoreObject(BaseModel):
    """Score as a structured {home, away} object.

    Accepts a [home, away] list/tuple during ingestion so the model
    can be constructed directly from pipeline JSON without an intermediate helper.
    """

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    home: int = Field(..., alias="home")
    away: int = Field(..., alias="away")

    @model_validator(mode="before")
    @classmethod
    def coerce_list(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            return {"home": v[0], "away": v[1]}
        return v


def _score_obj(home: int | None, away: int | None) -> "ScoreObject | None":
    """Build a ScoreObject from nullable ints; returns None if both are None."""
    if home is None and away is None:
        return None
    return ScoreObject(home=home or 0, away=away or 0)


class NormalizedStat(BaseModel):
    """A single normalized stat with canonical key and display label."""

    model_config = ConfigDict(populate_by_name=True)

    key: str
    display_label: str = Field(..., alias="displayLabel")
    group: str
    value: int | float | str | None = None
    format_type: str = Field("int", alias="formatType")


class TeamStat(BaseModel):
    """Team boxscore stats with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    is_home: bool = Field(..., alias="isHome")
    stats: dict[str, Any]
    source: str | None = None
    updated_at: datetime | None = Field(None, alias="updatedAt")
    normalized_stats: list[NormalizedStat] | None = Field(None, alias="normalizedStats")


class PlayerStat(BaseModel):
    """Generic player stat for NBA/NCAAB with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    minutes: float | None = None
    points: int | None = None
    rebounds: int | None = None
    assists: int | None = None
    raw_stats: dict[str, Any] = Field(default_factory=dict, alias="rawStats")
    source: str | None = None
    updated_at: datetime | None = Field(None, alias="updatedAt")
    normalized_stats: list[NormalizedStat] | None = Field(None, alias="normalizedStats")


class NHLSkaterStat(BaseModel):
    """NHL skater (non-goalie) stats with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    # Time on ice in MM:SS format
    toi: str | None = None
    goals: int | None = None
    assists: int | None = None
    points: int | None = None
    shots_on_goal: int | None = Field(None, alias="shotsOnGoal")
    plus_minus: int | None = Field(None, alias="plusMinus")
    penalty_minutes: int | None = Field(None, alias="penaltyMinutes")
    hits: int | None = None
    blocked_shots: int | None = Field(None, alias="blockedShots")
    raw_stats: dict[str, Any] = Field(default_factory=dict, alias="rawStats")
    source: str | None = None
    updated_at: datetime | None = Field(None, alias="updatedAt")


class NHLGoalieStat(BaseModel):
    """NHL goalie stats with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    # Time on ice in MM:SS format
    toi: str | None = None
    shots_against: int | None = Field(None, alias="shotsAgainst")
    saves: int | None = None
    goals_against: int | None = Field(None, alias="goalsAgainst")
    save_percentage: float | None = Field(None, alias="savePercentage")
    raw_stats: dict[str, Any] = Field(default_factory=dict, alias="rawStats")
    source: str | None = None
    updated_at: datetime | None = Field(None, alias="updatedAt")


class MLBBatterStat(BaseModel):
    """MLB batter stats with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    position: str | None = None
    at_bats: int | None = Field(None, alias="atBats")
    hits: int | None = None
    runs: int | None = None
    rbi: int | None = None
    home_runs: int | None = Field(None, alias="homeRuns")
    base_on_balls: int | None = Field(None, alias="baseOnBalls")
    strike_outs: int | None = Field(None, alias="strikeOuts")
    stolen_bases: int | None = Field(None, alias="stolenBases")
    avg: str | None = None
    obp: str | None = None
    slg: str | None = None
    ops: str | None = None
    raw_stats: dict[str, Any] = Field(default_factory=dict, alias="rawStats")
    source: str | None = None
    updated_at: datetime | None = Field(None, alias="updatedAt")


class MLBPitcherStat(BaseModel):
    """MLB pitcher stats with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    innings_pitched: str | None = Field(None, alias="inningsPitched")
    hits: int | None = None
    runs: int | None = None
    earned_runs: int | None = Field(None, alias="earnedRuns")
    base_on_balls: int | None = Field(None, alias="baseOnBalls")
    strike_outs: int | None = Field(None, alias="strikeOuts")
    home_runs: int | None = Field(None, alias="homeRuns")
    era: str | None = None
    pitch_count: int | None = Field(None, alias="pitchCount")
    strikes: int | None = None
    raw_stats: dict[str, Any] = Field(default_factory=dict, alias="rawStats")
    source: str | None = None
    updated_at: datetime | None = Field(None, alias="updatedAt")


class OddsEntry(BaseModel):
    """Odds entry with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    book: str
    market_type: str = Field(..., alias="marketType")
    market_category: str = Field("mainline", alias="marketCategory")
    player_name: str | None = Field(None, alias="playerName")
    description: str | None = None
    side: str | None = None
    line: float | None = None
    price: float | None = None
    is_closing_line: bool = Field(..., alias="isClosingLine")
    observed_at: datetime | None = Field(None, alias="observedAt")


class GamePhase(str, Enum):
    pregame = "pregame"
    in_game = "in_game"
    postgame = "postgame"
    unknown = "unknown"


class MediaType(str, Enum):
    video = "video"
    image = "image"


class SocialPostEntry(BaseModel):
    """Social post entry with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    post_url: str = Field(..., alias="postUrl")
    posted_at: datetime = Field(..., alias="postedAt")
    has_video: bool = Field(..., alias="hasVideo")
    team_abbreviation: str = Field(..., alias="teamAbbreviation")
    tweet_text: str | None = Field(None, alias="tweetText")
    video_url: str | None = Field(None, alias="videoUrl")
    image_url: str | None = Field(None, alias="imageUrl")
    source_handle: str | None = Field(None, alias="sourceHandle")
    media_type: MediaType | None = Field(None, alias="mediaType")
    game_phase: GamePhase = Field(GamePhase.unknown, alias="gamePhase")


class LiveSnapshot(BaseModel):
    """Live game snapshot for at-a-glance display."""

    model_config = ConfigDict(populate_by_name=True)

    period_label: str | None = Field(None, alias="periodLabel")
    time_label: str | None = Field(None, alias="timeLabel")
    score: ScoreObject | None = None
    current_period: int | None = Field(None, alias="currentPeriod")
    game_clock: str | None = Field(None, alias="gameClock")


class PlayEntry(BaseModel):
    """Play entry with camelCase output."""

    model_config = ConfigDict(populate_by_name=True)

    play_index: int = Field(..., alias="playIndex")
    quarter: int | None = None
    game_clock: str | None = Field(None, alias="gameClock")
    period_label: str | None = Field(None, alias="periodLabel")
    time_label: str | None = Field(None, alias="timeLabel")
    play_type: str | None = Field(None, alias="playType")
    team_abbreviation: str | None = Field(None, alias="teamAbbreviation")
    player_name: str | None = Field(None, alias="playerName")
    description: str | None = None
    score: ScoreObject | None = None
    tier: int | None = None
    score_changed: bool | None = Field(None, alias="scoreChanged")
    scoring_team_abbr: str | None = Field(None, alias="scoringTeamAbbr")
    points_scored: int | None = Field(None, alias="pointsScored")
    score_before: ScoreObject | None = Field(None, alias="scoreBefore")
    phase: str | None = None


class TieredPlayGroup(BaseModel):
    """Group of consecutive Tier-3 plays collapsed into a summary."""

    model_config = ConfigDict(populate_by_name=True)

    start_index: int = Field(..., alias="startIndex")
    end_index: int = Field(..., alias="endIndex")
    play_indices: list[int] = Field(..., alias="playIndices")
    summary_label: str = Field(..., alias="summaryLabel")


class NHLDataHealth(BaseModel):
    """NHL-specific data health indicators with camelCase output.

    Helps distinguish between legitimate empty data vs ingestion failure.
    Only populated for NHL games.
    """

    model_config = ConfigDict(populate_by_name=True)

    skater_count: int = Field(0, alias="skaterCount")
    goalie_count: int = Field(0, alias="goalieCount")
    is_healthy: bool = Field(True, alias="isHealthy")
    issues: list[str] = Field(default_factory=list)
