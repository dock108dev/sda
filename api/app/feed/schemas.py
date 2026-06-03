"""Schemas for the cross-sport narrative card feed."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.routers.sports.schemas.common import (
    PlayerStat,
    PlayImportance,
    PlayModeEligibility,
    ScoreObject,
    TeamStat,
)

CARD_FEED_CONTRACT_VERSION = 2


class CardFeedStatus(str, Enum):
    """Functional feed states clients can render without inference."""

    no_pbp_yet = "no_pbp_yet"
    unsupported_sport = "unsupported_sport"
    generation_pending = "generation_pending"
    validation_blocked = "validation_blocked"
    stale_regenerating = "stale_regenerating"
    ready = "ready"


class ScoreChange(BaseModel):
    """Per-card score delta."""

    model_config = ConfigDict(populate_by_name=True)

    home: int = 0
    away: int = 0


class CardPeriod(BaseModel):
    """Display period metadata for a card."""

    model_config = ConfigDict(populate_by_name=True)

    ordinal: int | None = None
    label: str | None = None
    type: str | None = None


class CardSituation(BaseModel):
    """Renderable situation summary plus source detail for sport adapters."""

    model_config = ConfigDict(populate_by_name=True)

    summary: str | None = None
    raw: dict[str, Any] | None = None


class CardTeam(BaseModel):
    """Team attribution for a feed card."""

    model_config = ConfigDict(populate_by_name=True)

    abbreviation: str | None = None
    name: str | None = None
    side: Literal["home", "away", "unknown"] = "unknown"


class CardSectionLeadIn(BaseModel):
    """Lead-in copy for a deterministic feed section."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: Literal["period"] = "period"
    ordinal: int
    period: CardPeriod
    label: str
    title: str
    lead_in: str = Field(..., alias="leadIn")
    start_play_index: int = Field(..., alias="startPlayIndex")
    end_play_index: int = Field(..., alias="endPlayIndex")
    source: Literal["generated", "deterministic", "fallback"] = "deterministic"


class NarrativeCard(BaseModel):
    """Backend-owned card payload for cross-sport clients."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    game_id: int = Field(..., alias="gameId")
    source_play_id: str = Field(..., alias="sourcePlayId")
    play_index: int = Field(..., alias="playIndex")
    sport: str
    league: str
    tier: int
    content_depth: Literal["extended", "standard", "brief"] = Field(
        ..., alias="contentDepth"
    )
    mode_eligibility: PlayModeEligibility = Field(..., alias="modeEligibility")
    importance: PlayImportance
    render_type: Literal[
        "important_narrative", "standard_pbp", "full_pbp", "play_unavailable"
    ] = Field(..., alias="renderType")
    visual_importance: Literal["critical", "high", "medium", "low"] = Field(
        ..., alias="visualImportance"
    )
    period_label: str | None = Field(None, alias="periodLabel")
    period: CardPeriod
    display_time: str | None = Field(None, alias="displayTime")
    clock: str | None = None
    team: CardTeam
    team_display: str | None = Field(None, alias="teamDisplay")
    team_context: str | None = Field(None, alias="teamContext")
    score_before: ScoreObject | None = Field(None, alias="scoreBefore")
    score_change: ScoreChange | None = Field(None, alias="scoreChange")
    score_after: ScoreObject | None = Field(None, alias="scoreAfter")
    score_before_display: str | None = Field(None, alias="scoreBeforeDisplay")
    score_after_display: str | None = Field(None, alias="scoreAfterDisplay")
    situation_before_display: str | None = Field(None, alias="situationBeforeDisplay")
    situation_after_display: str | None = Field(None, alias="situationAfterDisplay")
    situation: CardSituation
    lead_in: str = Field(..., alias="leadIn")
    stage_setting: str = Field(..., alias="stageSetting")
    headline: str
    description: str
    setup_line: str | None = Field(None, alias="setupLine")
    play_line: str | None = Field(None, alias="playLine")
    update_line: str | None = Field(None, alias="updateLine")
    raw_play_text: str | None = Field(None, alias="rawPlayText")
    event_type: str | None = Field(None, alias="eventType")
    full_details: dict[str, Any] | None = Field(None, alias="fullDetails")
    impact: str | None = None
    tags: list[str] = Field(default_factory=list)


class FeedGenerationStatus(BaseModel):
    """Card generation state and safe progress metadata."""

    model_config = ConfigDict(populate_by_name=True)

    status: CardFeedStatus
    card_count: int = Field(0, alias="cardCount")
    last_play_index: int | None = Field(None, alias="lastPlayIndex")
    generated_at: datetime | None = Field(None, alias="generatedAt")
    is_stale: bool = Field(False, alias="isStale")
    validation_issues: list[str] = Field(default_factory=list, alias="validationIssues")


class CardScoreboardCompetitor(BaseModel):
    """Team row for the normalized feed line score."""

    model_config = ConfigDict(populate_by_name=True)

    side: Literal["away", "home"]
    team_name: str | None = Field(None, alias="teamName")
    team_abbreviation: str | None = Field(None, alias="teamAbbreviation")
    score: int | None = None
    score_text: str | None = Field(None, alias="scoreText")
    is_winner: bool | None = Field(None, alias="isWinner")


class CardScoreboardSegment(BaseModel):
    """One period/inning/quarter score column."""

    model_config = ConfigDict(populate_by_name=True)

    label: str
    away: str | None = None
    home: str | None = None


class CardScoreboardTotals(BaseModel):
    """Final/current totals keyed by home/away side."""

    model_config = ConfigDict(populate_by_name=True)

    away: str | None = None
    home: str | None = None


class CardScoreboard(BaseModel):
    """Compact scoreboard payload clients can render without recomputing line score."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(1, alias="schemaVersion")
    layout: Literal["period_table", "inning_table", "quarter_table"] = "period_table"
    status_label: str | None = Field(None, alias="statusLabel")
    scoreline: str | None = None
    competitors: list[CardScoreboardCompetitor] = Field(default_factory=list)
    segments: list[CardScoreboardSegment] = Field(default_factory=list)
    totals: CardScoreboardTotals | None = None


class CardGameMetadata(BaseModel):
    """Game metadata for the feed envelope."""

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    sport: str
    league: str
    status: str | None = None
    home_team: str | None = Field(None, alias="homeTeam")
    away_team: str | None = Field(None, alias="awayTeam")
    home_team_id: int | None = Field(None, alias="homeTeamId")
    away_team_id: int | None = Field(None, alias="awayTeamId")
    home_team_abbr: str | None = Field(None, alias="homeTeamAbbr")
    away_team_abbr: str | None = Field(None, alias="awayTeamAbbr")
    score: ScoreObject | None = None
    scoreboard: CardScoreboard | None = None


class CardFeedResponse(BaseModel):
    """Renderable response envelope for game narrative cards."""

    model_config = ConfigDict(populate_by_name=True)

    contract_version: int = Field(CARD_FEED_CONTRACT_VERSION, alias="contractVersion")
    game: CardGameMetadata
    generation: FeedGenerationStatus
    sections: list[CardSectionLeadIn] = Field(default_factory=list)
    team_stats: list[TeamStat] = Field(default_factory=list, alias="teamStats")
    player_stats: list[PlayerStat] = Field(default_factory=list, alias="playerStats")
    cards: list[NarrativeCard] = Field(default_factory=list)
