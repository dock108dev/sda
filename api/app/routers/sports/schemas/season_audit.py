"""Season audit response schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SeasonAuditResponse(BaseModel):
    """Season-level data completeness audit."""

    model_config = ConfigDict(populate_by_name=True)

    league_code: str = Field(..., alias="leagueCode")
    season: int
    season_type: str = Field(..., alias="seasonType")

    # Game counts
    total_games: int = Field(..., alias="totalGames")
    expected_games: int | None = Field(None, alias="expectedGames")
    coverage_pct: float | None = Field(None, alias="coveragePct")

    # Data completeness counts
    with_boxscore: int = Field(0, alias="withBoxscore")
    with_player_stats: int = Field(0, alias="withPlayerStats")
    with_odds: int = Field(0, alias="withOdds")
    with_pbp: int = Field(0, alias="withPbp")
    with_social: int = Field(0, alias="withSocial")
    with_flow: int = Field(0, alias="withFlow")
    with_advanced_stats: int = Field(0, alias="withAdvancedStats")

    # Derived percentages (of total_games)
    boxscore_pct: float = Field(0, alias="boxscorePct")
    player_stats_pct: float = Field(0, alias="playerStatsPct")
    odds_pct: float = Field(0, alias="oddsPct")
    pbp_pct: float = Field(0, alias="pbpPct")
    social_pct: float = Field(0, alias="socialPct")
    flow_pct: float = Field(0, alias="flowPct")
    advanced_stats_pct: float = Field(0, alias="advancedStatsPct")

    # Team health
    teams_with_games: int = Field(0, alias="teamsWithGames")
    expected_teams: int | None = Field(None, alias="expectedTeams")

    # Season calendar
    season_start: str | None = Field(None, alias="seasonStart")   # e.g. "Oct 22, 2025"
    season_end: str | None = Field(None, alias="seasonEnd")       # e.g. "Apr 13, 2026"
    season_pct_complete: float | None = Field(None, alias="seasonPctComplete")  # 0-100
    expected_games_to_date: int | None = Field(None, alias="expectedGamesToDate")
