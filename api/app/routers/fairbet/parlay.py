"""FairBet parlay evaluation endpoint.

Computes combined fair probability and fair American odds for a parlay
from individual leg true probabilities — so clients don't need to
duplicate multiplication + odds conversion logic.
"""

from __future__ import annotations

import math

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...services.ev import implied_to_american

router = APIRouter()


class ParlayLeg(BaseModel):
    """A single leg in a parlay evaluation request."""

    true_prob: float = Field(..., gt=0, lt=1, alias="trueProb")
    confidence: float | None = Field(None, ge=0, le=1)


class ParlayEvaluateRequest(BaseModel):
    """Request body for parlay evaluation."""

    legs: list[ParlayLeg] = Field(..., min_length=2, max_length=20)


class ParlayEvaluateResponse(BaseModel):
    """Response from parlay evaluation."""

    fair_probability: float = Field(..., alias="fairProbability")
    fair_american_odds: int | None = Field(None, alias="fairAmericanOdds")
    combined_confidence: float = Field(..., alias="combinedConfidence")
    leg_count: int = Field(..., alias="legCount")


@router.post("/parlay/evaluate", response_model=ParlayEvaluateResponse)
async def evaluate_parlay(request: ParlayEvaluateRequest) -> ParlayEvaluateResponse:
    """Evaluate a parlay by multiplying true probabilities.

    Returns the combined fair probability, fair American odds, and
    a combined confidence score (geometric mean of leg confidences).
    """
    fair_prob = math.prod(leg.true_prob for leg in request.legs)

    fair_odds: int | None = None
    raw_odds = implied_to_american(fair_prob)
    if raw_odds != 0.0:
        fair_odds = round(raw_odds)

    # Combined confidence: geometric mean of leg confidences
    confidences = [leg.confidence for leg in request.legs if leg.confidence is not None]
    combined_confidence = math.prod(confidences) ** (1.0 / len(confidences)) if confidences else 1.0

    return ParlayEvaluateResponse(
        fair_probability=round(fair_prob, 6),
        fair_american_odds=fair_odds,
        combined_confidence=round(combined_confidence, 4),
        leg_count=len(request.legs),
    )
