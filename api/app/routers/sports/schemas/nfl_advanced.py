"""NFL advanced stats Pydantic schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NFLAdvancedTeamStats(BaseModel):
    """Team-level advanced EPA/WPA stats (nflverse-derived)."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    is_home: bool = Field(..., alias="isHome")

    # EPA metrics
    total_epa: float | None = Field(None, alias="totalEpa")
    pass_epa: float | None = Field(None, alias="passEpa")
    rush_epa: float | None = Field(None, alias="rushEpa")
    epa_per_play: float | None = Field(None, alias="epaPerPlay")

    # WPA
    total_wpa: float | None = Field(None, alias="totalWpa")

    # Success rates
    success_rate: float | None = Field(None, alias="successRate")
    pass_success_rate: float | None = Field(None, alias="passSuccessRate")
    rush_success_rate: float | None = Field(None, alias="rushSuccessRate")

    # Explosive plays
    explosive_play_rate: float | None = Field(None, alias="explosivePlayRate")

    # Passing context
    avg_cpoe: float | None = Field(None, alias="avgCpoe")
    avg_air_yards: float | None = Field(None, alias="avgAirYards")
    avg_yac: float | None = Field(None, alias="avgYac")

    # Volume
    total_plays: int | None = Field(None, alias="totalPlays")
    pass_plays: int | None = Field(None, alias="passPlays")
    rush_plays: int | None = Field(None, alias="rushPlays")


class NFLAdvancedPlayerStats(BaseModel):
    """Player-level advanced EPA/WPA stats (nflverse-derived)."""

    model_config = ConfigDict(populate_by_name=True)

    team: str
    player_name: str = Field(..., alias="playerName")
    is_home: bool = Field(..., alias="isHome")
    player_role: str | None = Field(None, alias="playerRole")

    # EPA
    total_epa: float | None = Field(None, alias="totalEpa")
    epa_per_play: float | None = Field(None, alias="epaPerPlay")

    # Role-specific EPA
    pass_epa: float | None = Field(None, alias="passEpa")
    rush_epa: float | None = Field(None, alias="rushEpa")
    receiving_epa: float | None = Field(None, alias="receivingEpa")

    # Passing
    cpoe: float | None = None
    air_epa: float | None = Field(None, alias="airEpa")
    yac_epa: float | None = Field(None, alias="yacEpa")
    air_yards: float | None = Field(None, alias="airYards")

    # WPA
    total_wpa: float | None = Field(None, alias="totalWpa")

    # Success
    success_rate: float | None = Field(None, alias="successRate")

    # Volume
    plays: int | None = None
