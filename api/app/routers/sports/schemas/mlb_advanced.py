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
    batters_faced: int | None = Field(None, alias="battersFaced")
    pitches_thrown: int | None = Field(None, alias="pitchesThrown")
    strikeouts: int | None = None
    walks: int | None = None
    # Raw Statcast counts
    zone_pitches: int | None = Field(None, alias="zonePitches")
    zone_swings: int | None = Field(None, alias="zoneSwings")
    zone_contact: int | None = Field(None, alias="zoneContact")
    outside_pitches: int | None = Field(None, alias="outsidePitches")
    outside_swings: int | None = Field(None, alias="outsideSwings")
    outside_contact: int | None = Field(None, alias="outsideContact")
    balls_in_play: int | None = Field(None, alias="ballsInPlay")
    avg_exit_velo_against: float | None = Field(None, alias="avgExitVeloAgainst")
    hard_hit_against: int | None = Field(None, alias="hardHitAgainst")
    barrel_against: int | None = Field(None, alias="barrelAgainst")


class MLBFieldingStatSchema(BaseModel):
    """Per-game fielding stats per player."""

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


class MLBAdvancedPlayerStats(BaseModel):
    """Player-level advanced batting stats (Statcast-derived)."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    is_home: bool = Field(..., alias="isHome")

    # Raw Statcast counts
    total_pitches: int = Field(..., alias="totalPitches")
    zone_pitches: int = Field(0, alias="zonePitches")
    zone_swings: int = Field(0, alias="zoneSwings")
    zone_contact: int = Field(0, alias="zoneContact")
    outside_pitches: int = Field(0, alias="outsidePitches")
    outside_swings: int = Field(0, alias="outsideSwings")
    outside_contact: int = Field(0, alias="outsideContact")
    balls_in_play: int = Field(..., alias="ballsInPlay")
    avg_exit_velo: float | None = Field(None, alias="avgExitVelo")
    hard_hit_count: int = Field(0, alias="hardHitCount")
    barrel_count: int = Field(0, alias="barrelCount")
