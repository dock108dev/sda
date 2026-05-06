"""Game Flow API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import ScoreObject

__all__ = ["ScoreObject"]


class MomentPlayerStat(BaseModel):
    """Player stat entry for cumulative box score."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    # Basketball stats
    pts: int | None = None
    reb: int | None = None
    ast: int | None = None
    three_pm: int | None = Field(None, alias="3pm")
    # Hockey stats
    goals: int | None = None
    assists: int | None = None
    sog: int | None = None
    plus_minus: int | None = Field(None, alias="plusMinus")


class MomentGoalieStat(BaseModel):
    """Goalie stat entry for NHL box score."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    saves: int
    ga: int
    save_pct: float = Field(..., alias="savePct")


class MomentTeamBoxScore(BaseModel):
    """Team box score for a moment."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    score: int
    players: list[MomentPlayerStat]
    goalie: MomentGoalieStat | None = None


class MomentBoxScore(BaseModel):
    """Cumulative box score at a moment in time."""

    model_config = ConfigDict(populate_by_name=True)

    home: MomentTeamBoxScore
    away: MomentTeamBoxScore


class GameFlowMoment(BaseModel):
    """A single condensed moment in the Game Flow.

    This matches the Game Flow contract exactly:
    - play_ids: All plays in this moment
    - explicitly_narrated_play_ids: Plays that must be narrated
    - period/clock/score: Context metadata
    - narrative: AI-generated narrative text
    - cumulative_box_score: Running player stats snapshot at this moment
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    play_ids: list[int] = Field(..., alias="playIds")
    explicitly_narrated_play_ids: list[int] = Field(..., alias="explicitlyNarratedPlayIds")
    period: int
    start_clock: str | None = Field(None, alias="startClock")
    end_clock: str | None = Field(None, alias="endClock")
    score_before: ScoreObject = Field(..., alias="scoreBefore")
    score_after: ScoreObject = Field(..., alias="scoreAfter")
    narrative: str | None = None  # Narrative is in blocks_json, not moments_json
    cumulative_box_score: MomentBoxScore | None = Field(None, alias="cumulativeBoxScore")


class GameFlowPlay(BaseModel):
    """A play referenced by a Game Flow moment.

    Only plays referenced in moments are included.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    play_id: int = Field(..., alias="playId")
    play_index: int = Field(..., alias="playIndex")
    period: int
    clock: str | None
    play_type: str | None = Field(None, alias="playType")
    description: str | None
    score: ScoreObject | None = None


class GameFlowContent(BaseModel):
    """The Game Flow content containing ordered moments."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    moments: list[GameFlowMoment]


class BlockMiniBox(BaseModel):
    """Mini box score for a narrative block with cumulative stats and segment deltas."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    home: dict[str, Any]  # {team, players: [{name, pts, deltaPts, ...}]}
    away: dict[str, Any]
    block_stars: list[str] = Field(default_factory=list, alias="blockStars")


class FeaturedPlayer(BaseModel):
    """A player called out within a block. The reason field anchors the
    callout to a causal moment in the segment (lead-change scorer, run owner,
    late-game closer, decisive event) so player mentions act as evidence,
    not decoration."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    name: str
    team: str | None = None
    role: str | None = None  # e.g. "lead_change_scorer", "run_owner", "late_closer"
    reason: str  # required: the segment-causal explanation
    stat_summary: str | None = Field(None, alias="statSummary")


class ScoreContext(BaseModel):
    """Score-state context for a narrative block. Distinct from score_before /
    score_after (which are raw [home, away] tuples) — this layer carries
    derived signals the consumer + validator both need: whether the block
    contained a lead change, and the largest single-direction margin swing
    inside the block."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    start_score: ScoreObject | None = Field(None, alias="startScore")
    end_score: ScoreObject | None = Field(None, alias="endScore")
    lead_change: bool = Field(False, alias="leadChange")
    largest_lead_delta: int | None = Field(None, alias="largestLeadDelta")


class GameFlowBlock(BaseModel):
    """A narrative block grouping multiple moments.

    Blocks are the consumer-facing narrative output.
    Each block represents a stretch of play described in 1-2 sentences.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    block_index: int = Field(..., alias="blockIndex")
    role: str  # SemanticRole value: SETUP, MOMENTUM_SHIFT, RESPONSE, DECISION_POINT, RESOLUTION
    moment_indices: list[int] = Field(..., alias="momentIndices")
    period_start: int = Field(..., alias="periodStart")
    period_end: int = Field(..., alias="periodEnd")
    score_before: ScoreObject = Field(..., alias="scoreBefore")
    score_after: ScoreObject = Field(..., alias="scoreAfter")
    play_ids: list[int] = Field(..., alias="playIds")
    key_play_ids: list[int] = Field(..., alias="keyPlayIds")
    narrative: str | None = None
    mini_box: BlockMiniBox | None = Field(None, alias="miniBox")
    embedded_social_post_id: int | None = Field(None, alias="embeddedSocialPostId")
    start_clock: str | None = Field(None, alias="startClock")
    end_clock: str | None = Field(None, alias="endClock")
    # v2 schema fields — nullable for backward compatibility with v1 readers.
    reason: str | None = None
    label: str | None = None
    lead_before: int | None = Field(None, alias="leadBefore")
    lead_after: int | None = Field(None, alias="leadAfter")
    evidence: list[dict[str, Any]] | None = None
    # v3 schema fields — segmentation/voice contract per the gameflow brief.
    # Optional so v2 rows continue to serialize; populated by the v3 generator.
    story_role: str | None = Field(None, alias="storyRole")
    leverage: str | None = None  # "low" | "medium" | "high"
    period_range: str | None = Field(None, alias="periodRange")
    featured_players: list[FeaturedPlayer] | None = Field(None, alias="featuredPlayers")
    score_context: ScoreContext | None = Field(None, alias="scoreContext")


class GameFlowResponse(BaseModel):
    """Response for GET /games/{game_id}/flow.

    Returns the persisted Game Flow exactly as stored.
    No transformation, no aggregation, no additional prose.

    Additional fields:
    - blocks: 4-7 narrative blocks (consumer-facing output)
    - total_words: Total word count across all block narratives
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    flow: GameFlowContent
    plays: list[GameFlowPlay]
    validation_passed: bool = Field(..., alias="validationPassed")
    validation_errors: list[str] = Field(default_factory=list, alias="validationErrors")
    blocks: list[GameFlowBlock] | None = None
    total_words: int | None = Field(None, alias="totalWords")
    home_team: str | None = Field(None, alias="homeTeam")
    away_team: str | None = Field(None, alias="awayTeam")
    home_team_abbr: str | None = Field(None, alias="homeTeamAbbr")
    away_team_abbr: str | None = Field(None, alias="awayTeamAbbr")
    home_team_color_light: str | None = Field(None, alias="homeTeamColorLight")
    home_team_color_dark: str | None = Field(None, alias="homeTeamColorDark")
    away_team_color_light: str | None = Field(None, alias="awayTeamColorLight")
    away_team_color_dark: str | None = Field(None, alias="awayTeamColorDark")
    league_code: str | None = Field(None, alias="leagueCode")
    # v2 schema top-level fields (BRAINDUMP §Output schema). Nullable so v1
    # readers and historical rows without these columns continue to work.
    version: str | None = None
    archetype: str | None = None
    winner_team_id: str | None = Field(None, alias="winnerTeamId")
    source_counts: dict[str, Any] | None = Field(None, alias="sourceCounts")
    validation: dict[str, Any] | None = None


class ConsumerGameFlowResponse(BaseModel):
    """Consumer-safe Game Flow response for GET /api/v1/games/{id}/flow.

    Blocks are the consumer contract. Moments are pipeline-internal and
    not exposed here. Admin tooling uses GameFlowResponse instead.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    plays: list[GameFlowPlay]
    blocks: list[GameFlowBlock] = Field(default_factory=list)
    total_words: int | None = Field(None, alias="totalWords")
    home_team: str | None = Field(None, alias="homeTeam")
    away_team: str | None = Field(None, alias="awayTeam")
    home_team_abbr: str | None = Field(None, alias="homeTeamAbbr")
    away_team_abbr: str | None = Field(None, alias="awayTeamAbbr")
    home_team_color_light: str | None = Field(None, alias="homeTeamColorLight")
    home_team_color_dark: str | None = Field(None, alias="homeTeamColorDark")
    away_team_color_light: str | None = Field(None, alias="awayTeamColorLight")
    away_team_color_dark: str | None = Field(None, alias="awayTeamColorDark")
    league_code: str | None = Field(None, alias="leagueCode")
    # v2 schema top-level fields. Nullable so older rows still serialize.
    version: str | None = None
    archetype: str | None = None
    winner_team_id: str | None = Field(None, alias="winnerTeamId")
    source_counts: dict[str, Any] | None = Field(None, alias="sourceCounts")
    validation: dict[str, Any] | None = None


class FlowStatusResponse(BaseModel):
    """Returned when a flow is not yet available for a game.

    RECAP_PENDING: game is FINAL but flow generation is in progress.
    PREGAME / IN_PROGRESS / POSTPONED / CANCELED: non-final game states.
    """

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    status: str  # RECAP_PENDING | IN_PROGRESS | PREGAME | SCHEDULED | POSTPONED | CANCELED
    eta_minutes: int | None = Field(None, alias="etaMinutes")


class TimelineArtifactResponse(BaseModel):
    """Finalized timeline artifact response."""

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    sport: str
    timeline_version: str = Field(..., alias="timelineVersion")
    generated_at: datetime = Field(..., alias="generatedAt")
    timeline: list[dict[str, Any]]
    summary: dict[str, Any]
    game_analysis: dict[str, Any] = Field(..., alias="gameAnalysis")
