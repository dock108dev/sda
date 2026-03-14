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


class MLBPitcherGameStatSchema(BaseModel):
    """Per-pitcher game stats with Statcast metrics."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    is_starter: bool = Field(False, alias="isStarter")
    innings_pitched: float | None = Field(None, alias="inningsPitched")
    strikeouts: int | None = None
    walks: int | None = None
    k_rate: float | None = Field(None, alias="kRate")
    bb_rate: float | None = Field(None, alias="bbRate")
    whiff_rate: float | None = Field(None, alias="whiffRate")
    z_contact_pct: float | None = Field(None, alias="zContactPct")
    chase_rate: float | None = Field(None, alias="chaseRate")
    avg_exit_velo_against: float | None = Field(None, alias="avgExitVeloAgainst")
    hard_hit_pct_against: float | None = Field(None, alias="hardHitPctAgainst")
    barrel_pct_against: float | None = Field(None, alias="barrelPctAgainst")


class MLBFieldingStatSchema(BaseModel):
    """Season-level fielding stats per player."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    position: str | None = None
    outs_above_average: float | None = Field(None, alias="outsAboveAverage")
    defensive_runs_saved: float | None = Field(None, alias="defensiveRunsSaved")
    uzr: float | None = None
    errors: int | None = None
    assists: int | None = None
    putouts: int | None = None
    games_played: int | None = Field(None, alias="gamesPlayed")


class MLBAdvancedPlayerStats(BaseModel):
    """Player-level advanced batting stats (Statcast-derived)."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
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
