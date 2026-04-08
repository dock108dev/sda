"""Team-related Pydantic schemas."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TeamSummary(BaseModel):
    """Team summary for list view."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    short_name: str = Field(alias="shortName")
    abbreviation: str
    league_code: str = Field(alias="leagueCode")
    games_count: int = Field(alias="gamesCount")
    color_light_hex: str | None = Field(None, alias="colorLightHex")
    color_dark_hex: str | None = Field(None, alias="colorDarkHex")
    color_secondary_light_hex: str | None = Field(None, alias="colorSecondaryLightHex")
    color_secondary_dark_hex: str | None = Field(None, alias="colorSecondaryDarkHex")


class TeamListResponse(BaseModel):
    """Response for teams list endpoint."""

    teams: list[TeamSummary]
    total: int


class TeamGameSummary(BaseModel):
    """Game summary for team detail."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    game_date: str = Field(alias="gameDate")
    opponent: str
    is_home: bool = Field(alias="isHome")
    score: str
    result: str


class TeamDetail(BaseModel):
    """Team detail with recent games."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    short_name: str = Field(alias="shortName")
    abbreviation: str
    league_code: str = Field(alias="leagueCode")
    location: str | None
    external_ref: str | None = Field(alias="externalRef")
    x_handle: str | None = Field(None, alias="xHandle")
    x_profile_url: str | None = Field(None, alias="xProfileUrl")
    color_light_hex: str | None = Field(None, alias="colorLightHex")
    color_dark_hex: str | None = Field(None, alias="colorDarkHex")
    color_secondary_light_hex: str | None = Field(None, alias="colorSecondaryLightHex")
    color_secondary_dark_hex: str | None = Field(None, alias="colorSecondaryDarkHex")
    recent_games: list[TeamGameSummary] = Field(alias="recentGames")


class TeamSocialInfo(BaseModel):
    """Team social media information."""

    team_id: int = Field(..., alias="teamId")
    abbreviation: str
    x_handle: str | None = Field(None, alias="xHandle")
    x_profile_url: str | None = Field(None, alias="xProfileUrl")


_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _validate_hex_color(v: str | None) -> str | None:
    """Validate and normalize a hex color to uppercase #RRGGBB."""
    if v is None:
        return None
    if not isinstance(v, str) or not _HEX_COLOR_RE.fullmatch(v):
        raise ValueError("must be a #RRGGBB hex color (e.g. '#1A2B3C')")
    return v.upper()


class TeamColorUpdate(BaseModel):
    """Request body for updating team colors (primary and secondary)."""

    model_config = ConfigDict(populate_by_name=True)

    color_light_hex: str | None = Field(None, alias="colorLightHex")
    color_dark_hex: str | None = Field(None, alias="colorDarkHex")
    color_secondary_light_hex: str | None = Field(None, alias="colorSecondaryLightHex")
    color_secondary_dark_hex: str | None = Field(None, alias="colorSecondaryDarkHex")

    @field_validator(
        "color_light_hex",
        "color_dark_hex",
        "color_secondary_light_hex",
        "color_secondary_dark_hex",
        mode="before",
    )
    @classmethod
    def validate_hex(cls, v: str | None) -> str | None:
        return _validate_hex_color(v)
