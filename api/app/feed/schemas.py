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


class SpoilerPolicy(str, Enum):
    """Score disclosure policy for feed card responses."""

    pre_reveal = "pre_reveal"
    revealed = "revealed"


class CardFieldSpoilerLevel(str, Enum):
    """Disclosure level for generated text fields on a card."""

    pre_open_safe = "preOpenSafe"
    earned_at_play = "earnedAtPlay"
    reveal_only = "revealOnly"


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


class CardTextSpoilerLevels(BaseModel):
    """Spoiler levels for generated card text fields."""

    model_config = ConfigDict(populate_by_name=True)

    lead_in: CardFieldSpoilerLevel = Field(..., alias="leadIn")
    stage_setting: CardFieldSpoilerLevel = Field(..., alias="stageSetting")
    headline: CardFieldSpoilerLevel
    description: CardFieldSpoilerLevel
    impact: CardFieldSpoilerLevel | None = None
    situation_summary: CardFieldSpoilerLevel | None = Field(
        None, alias="situationSummary"
    )
    tags: CardFieldSpoilerLevel


class CardSectionLeadIn(BaseModel):
    """Spoiler-classified lead-in copy for a deterministic feed section."""

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
    text_field_spoiler_level: CardFieldSpoilerLevel = Field(
        CardFieldSpoilerLevel.earned_at_play,
        alias="textFieldSpoilerLevel",
    )
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
    spoiler_level: Literal["none", "score_change", "score_revealed"] = Field(
        ..., alias="spoilerLevel"
    )
    text_field_spoiler_levels: CardTextSpoilerLevels = Field(
        default_factory=lambda: CardTextSpoilerLevels(
            leadIn=CardFieldSpoilerLevel.earned_at_play,
            stageSetting=CardFieldSpoilerLevel.earned_at_play,
            headline=CardFieldSpoilerLevel.earned_at_play,
            description=CardFieldSpoilerLevel.earned_at_play,
            impact=CardFieldSpoilerLevel.earned_at_play,
            situationSummary=CardFieldSpoilerLevel.earned_at_play,
            tags=CardFieldSpoilerLevel.earned_at_play,
        ),
        alias="textFieldSpoilerLevels",
    )


class FeedGenerationStatus(BaseModel):
    """Card generation state and safe progress metadata."""

    model_config = ConfigDict(populate_by_name=True)

    status: CardFeedStatus
    card_count: int = Field(0, alias="cardCount")
    last_play_index: int | None = Field(None, alias="lastPlayIndex")
    generated_at: datetime | None = Field(None, alias="generatedAt")
    is_stale: bool = Field(False, alias="isStale")
    validation_issues: list[str] = Field(default_factory=list, alias="validationIssues")


class CompletedGameRevealBoundary(BaseModel):
    """Completed-game fields that are allowed only after the reveal boundary."""

    model_config = ConfigDict(populate_by_name=True)

    final_score: Literal["unavailable", "hidden_until_reveal", "allowed"] = Field(
        ..., alias="finalScore"
    )
    winner: Literal["unavailable", "hidden_until_reveal", "allowed"]
    stats: Literal["unavailable", "hidden_until_reveal", "allowed"]
    payoff_copy: Literal["unavailable", "hidden_until_reveal", "allowed"] = Field(
        ..., alias="payoffCopy"
    )


class RevealAvailability(BaseModel):
    """Spoiler-safe reveal capability metadata."""

    model_config = ConfigDict(populate_by_name=True)

    available: bool
    status: Literal["unavailable", "ready"]
    scores_in_cards: bool = Field(..., alias="scoresInCards")
    reveal_required_for_scores: bool = Field(..., alias="revealRequiredForScores")
    boundary: CompletedGameRevealBoundary = Field(..., alias="completedGameBoundary")


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


class CardFeedResponse(BaseModel):
    """Renderable response envelope for game narrative cards."""

    model_config = ConfigDict(populate_by_name=True)

    contract_version: int = Field(CARD_FEED_CONTRACT_VERSION, alias="contractVersion")
    game: CardGameMetadata
    spoiler_policy: SpoilerPolicy = Field(..., alias="spoilerPolicy")
    generation: FeedGenerationStatus
    reveal: RevealAvailability
    sections: list[CardSectionLeadIn] = Field(default_factory=list)
    team_stats: list[TeamStat] = Field(default_factory=list, alias="teamStats")
    player_stats: list[PlayerStat] = Field(default_factory=list, alias="playerStats")
    cards: list[NarrativeCard] = Field(default_factory=list)
