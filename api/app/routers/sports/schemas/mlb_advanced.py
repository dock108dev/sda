"""MLB advanced stats Pydantic schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MLBAdvancedTeamStats(BaseModel):
    """Team-level advanced batting stats (Statcast-derived)."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    is_home: bool = Field(..., alias="isHome")

    # Plate discipline
    total_pitches: int = Field(..., alias="totalPitches")
    z_swing_pct: float | None = Field(None, alias="zSwingPct")
    o_swing_pct: float | None = Field(None, alias="oSwingPct")
    z_contact_pct: float | None = Field(None, alias="zContactPct")
    o_contact_pct: float | None = Field(None, alias="oContactPct")

    # Quality of contact
    balls_in_play: int = Field(..., alias="ballsInPlay")
    avg_exit_velo: float | None = Field(None, alias="avgExitVelo")
    hard_hit_pct: float | None = Field(None, alias="hardHitPct")
    barrel_pct: float | None = Field(None, alias="barrelPct")
