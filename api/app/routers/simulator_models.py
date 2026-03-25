"""Shared Pydantic models for simulator endpoints.

Extracted to avoid circular imports between the generic multi-sport
router (``simulator.py``) and the MLB-specific router (``simulator_mlb.py``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreFrequency(BaseModel):
    """A final score and how often it occurred in the simulation."""

    score: str = Field(..., description="Final score as 'away-home' (e.g. '3-5')")
    probability: float = Field(
        ..., description="Fraction of simulations with this score (0–1)",
    )
