"""Pydantic response models for Entity Resolution endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TeamResolutionResult(BaseModel):
    """Single team resolution result."""

    model_config = _ALIAS_CFG

    source: str = Field(description="Source identifier (abbreviation)")
    resolved_id: int | None = Field(description="Internal team ID if resolved")
    resolved_name: str | None = Field(description="Resolved team name")
    status: str = Field(description="success, failed, ambiguous, partial")
    method: str | None = Field(description="Resolution method used")
    occurrences: int = Field(default=1, description="Times this team appeared")


class PlayerResolutionResult(BaseModel):
    """Single player resolution result."""

    model_config = _ALIAS_CFG

    source: str = Field(description="Source player name")
    resolved_name: str | None = Field(description="Normalized player name")
    status: str = Field(description="success, failed")
    method: str | None = Field(description="Resolution method used")
    occurrences: int = Field(default=1, description="Times this player appeared")


class ResolutionIssue(BaseModel):
    """Resolution issue requiring review."""

    model_config = _ALIAS_CFG

    source: str
    reason: str | None = None
    occurrences: int = Field(default=1)
    candidates: list[dict[str, Any]] | None = None


class ResolutionStats(BaseModel):
    """Stats for a category of resolutions."""

    model_config = _ALIAS_CFG

    total: int
    resolved: int
    failed: int
    resolution_rate: float


class ResolutionSummaryResponse(BaseModel):
    """Summary of all entity resolutions for a game or run."""

    model_config = _ALIAS_CFG

    game_id: int
    pipeline_run_id: int | None
    game_info: dict[str, Any] | None = Field(description="Game metadata")
    teams: ResolutionStats
    players: ResolutionStats
    team_resolutions: list[TeamResolutionResult]
    player_resolutions: list[PlayerResolutionResult]
    issues: dict[str, Any] = Field(
        description="Issues requiring review: unresolved_teams, ambiguous_teams, unresolved_players"
    )


class ResolutionDetailResponse(BaseModel):
    """Detailed resolution info for a single entity."""

    model_config = _ALIAS_CFG

    entity_type: str
    source_identifier: str
    resolved_id: int | None
    resolved_name: str | None
    status: str
    method: str | None
    confidence: float | None
    failure_reason: str | None
    candidates: list[dict[str, Any]] | None
    occurrence_count: int
    first_play_index: int | None
    last_play_index: int | None
    source_context: dict[str, Any] | None
