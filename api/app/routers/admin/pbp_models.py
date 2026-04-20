"""Response models for PBP admin endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.routers.sports.schemas.common import ScoreObject

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PlaySummary(BaseModel):
    """Summary of a single play for listing."""

    model_config = _ALIAS_CFG

    play_index: int
    quarter: int | None
    game_clock: str | None
    play_type: str | None
    team_abbreviation: str | None
    team_id: int | None
    team_resolved: bool
    player_name: str | None
    player_id: str | None
    description: str | None
    score: ScoreObject | None
    has_raw_data: bool


class PlayDetail(BaseModel):
    """Full detail of a single play."""

    model_config = _ALIAS_CFG

    play_index: int
    quarter: int | None
    game_clock: str | None
    play_type: str | None
    team_abbreviation: str | None
    team_id: int | None
    team_name: str | None
    player_name: str | None
    player_id: str | None
    description: str | None
    score: ScoreObject | None
    raw_data: dict[str, Any]
    created_at: str
    updated_at: str


class GamePBPResponse(BaseModel):
    """Current PBP data for a game from sports_game_plays table."""

    model_config = _ALIAS_CFG

    game_id: int
    game_date: str
    home_team: str
    away_team: str
    game_status: str
    total_plays: int
    plays: list[PlaySummary]
    resolution_summary: dict[str, Any] = Field(
        description="Summary of team/player resolution status"
    )


class GamePBPDetailResponse(BaseModel):
    """Detailed PBP data with full play information."""

    model_config = _ALIAS_CFG

    game_id: int
    game_date: str
    home_team: str
    home_team_id: int
    away_team: str
    away_team_id: int
    game_status: str
    total_plays: int
    plays: list[PlayDetail]
    resolution_summary: dict[str, Any]
    metadata: dict[str, Any] = Field(
        description="Additional metadata about the PBP data"
    )


class PBPSnapshotSummary(BaseModel):
    """Summary of a PBP snapshot."""

    model_config = _ALIAS_CFG

    snapshot_id: int
    game_id: int
    snapshot_type: str
    source: str | None
    play_count: int
    pipeline_run_id: int | None
    scrape_run_id: int | None
    created_at: str
    resolution_stats: dict[str, Any] | None


class PBPSnapshotDetail(BaseModel):
    """Full detail of a PBP snapshot."""

    model_config = _ALIAS_CFG

    snapshot_id: int
    game_id: int
    snapshot_type: str
    source: str | None
    play_count: int
    pipeline_run_id: int | None
    pipeline_run_uuid: str | None
    scrape_run_id: int | None
    plays: list[dict[str, Any]]
    metadata: dict[str, Any] | None
    resolution_stats: dict[str, Any] | None
    created_at: str


class GamePBPSnapshotsResponse(BaseModel):
    """All PBP snapshots for a game."""

    model_config = _ALIAS_CFG

    game_id: int
    game_date: str
    home_team: str
    away_team: str
    snapshots: list[PBPSnapshotSummary]
    total_snapshots: int
    has_raw: bool
    has_normalized: bool
    has_resolved: bool


class PipelineRunPBPResponse(BaseModel):
    """PBP data associated with a specific pipeline run."""

    model_config = _ALIAS_CFG

    run_id: int
    run_uuid: str
    game_id: int
    game_date: str
    home_team: str
    away_team: str
    normalized_pbp: dict[str, Any] | None = Field(
        description="Normalized PBP from NORMALIZE_PBP stage output"
    )
    play_count: int
    snapshot: PBPSnapshotSummary | None = Field(
        description="Associated PBP snapshot if one exists"
    )


class PBPComparisonResponse(BaseModel):
    """Compare PBP between current and snapshot."""

    model_config = _ALIAS_CFG

    game_id: int
    comparison_type: str
    current_play_count: int
    snapshot_play_count: int
    differences: dict[str, Any] = Field(
        description="Summary of differences between current and snapshot"
    )
