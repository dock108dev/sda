"""Pydantic schemas for the catch-up game summary API (v3-summary)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SummaryFinalScore(BaseModel):
    """Final score block returned with every game summary."""

    model_config = ConfigDict(populate_by_name=True)

    home: int
    away: int
    home_abbr: str | None = Field(None, alias="homeAbbr")
    away_abbr: str | None = Field(None, alias="awayAbbr")


class FlowStatusResponse(BaseModel):
    """Returned when a summary is not yet available for a game.

    RECAP_PENDING: game is FINAL but summary generation is in progress.
    PREGAME / IN_PROGRESS / POSTPONED / CANCELED: non-final game states.
    """

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    status: str
    eta_minutes: int | None = Field(None, alias="etaMinutes")


class TimelineArtifactResponse(BaseModel):
    """Finalized timeline artifact response (admin)."""

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    sport: str
    timeline_version: str = Field(..., alias="timelineVersion")
    generated_at: datetime = Field(..., alias="generatedAt")
    timeline: list[dict[str, Any]]
    summary: dict[str, Any]
    game_analysis: dict[str, Any] = Field(..., alias="gameAnalysis")


class GameSummaryResponse(BaseModel):
    """Consumer-facing response for ``GET /api/v1/games/{game_id}/summary``.

    Cached indefinitely after first generation. The ``summary`` field is a
    list of 3-5 paragraphs in narrative columnist tone. ``referencedPlayIds``
    are the play_index values of the plays the recap actually leans on, so
    catch-up cards can link back.
    """

    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(..., alias="gameId")
    sport: str
    final_score: SummaryFinalScore = Field(..., alias="finalScore")
    summary: list[str]
    referenced_play_ids: list[int] = Field(
        default_factory=list, alias="referencedPlayIds"
    )
    archetype: str | None = None
    generated_at: datetime = Field(..., alias="generatedAt")
    model_used: str | None = Field(None, alias="modelUsed")
    story_version: str = Field("v3-summary", alias="storyVersion")
    home_team: str | None = Field(None, alias="homeTeam")
    away_team: str | None = Field(None, alias="awayTeam")
    league_code: str | None = Field(None, alias="leagueCode")
