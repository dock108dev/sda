"""Schemas for card-generation debug inspection."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CardGenerationDebugFinding(BaseModel):
    """Admin-facing finding for narrative card generation inspection."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    play_id: str | None = Field(None, alias="playId")
    scope: str | None = None


class CardGenerationDebugResponse(BaseModel):
    """Admin-only envelope for inspecting cross-sport card generation."""

    model_config = ConfigDict(populate_by_name=True)

    available: bool
    status: Literal["available", "not_available", "blocked"]
    reason: str | None = None
    policy: Literal["live", "official"] | None = None
    card_count: int = Field(0, alias="cardCount")
    last_play_index: int | None = Field(None, alias="lastPlayIndex")
    generation_version: str | None = Field(None, alias="generationVersion")
    source_hash: str | None = Field(None, alias="sourceHash")
    cache_state: str = Field(..., alias="cacheState")
    warnings: list[CardGenerationDebugFinding] = Field(default_factory=list)
    errors: list[CardGenerationDebugFinding] = Field(default_factory=list)
    feed: dict[str, Any] | None = None
