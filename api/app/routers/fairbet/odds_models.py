"""Pydantic response models for FairBet odds endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .ev_annotation import BookOdds


class ExplanationDetailRow(BaseModel):
    """A single key-value row in an explanation step."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    label: str
    value: str
    is_highlight: bool = False


class ExplanationStep(BaseModel):
    """One step in the math walkthrough for derived fair odds."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    step_number: int
    title: str
    description: str
    detail_rows: list[ExplanationDetailRow] = []


class BetDefinition(BaseModel):
    """A unique bet definition with odds from all books."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    game_id: int
    league_code: str
    home_team: str
    away_team: str
    game_date: datetime
    market_key: str
    selection_key: str
    line_value: float
    market_category: str | None = None
    player_name: str | None = None
    description: str | None = None
    true_prob: float | None = None
    reference_price: float | None = None
    opposite_reference_price: float | None = None
    books: list[BookOdds]
    ev_confidence_tier: str | None = None
    ev_disabled_reason: str | None = None
    ev_method: str | None = None
    has_fair: bool = False
    estimated_sharp_price: float | None = None
    extrapolation_ref_line: float | None = None
    extrapolation_distance: float | None = None
    consensus_book_count: int | None = None
    consensus_iqr: float | None = None
    per_book_fair_probs: dict[str, float] | None = None
    confidence: float | None = None
    confidence_flags: list[str] = []
    fair_american_odds: int | None = None
    selection_display: str | None = None
    market_display_name: str | None = None
    best_book: str | None = None
    best_ev_percent: float | None = None
    is_reliably_positive: bool | None = None
    confidence_display_label: str | None = None
    ev_method_display_name: str | None = None
    ev_method_explanation: str | None = None
    explanation_steps: list[ExplanationStep] | None = None


class FairbetOddsResponse(BaseModel):
    """Paginated FairBet odds response with compatibility fields."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    bets: list[BetDefinition]
    items: list[BetDefinition] = []
    nextCursor: str | None = None
    hasMore: bool = False
    total: int | None = None
    generatedAt: datetime | None = None
    snapshotId: str | None = None
    requestId: str | None = None
    pageLatencyMs: int | None = None
    partial: bool = False
    warnings: list[str] = []
    books_available: list[str] = []
    market_categories_available: list[str] = []
    games_available: list[dict[str, Any]] = []
    ev_diagnostics: dict[str, int] = {}
    ev_config: dict[str, Any] | None = None
