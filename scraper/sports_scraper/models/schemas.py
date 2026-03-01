"""Pydantic models used by scrapers and odds clients."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SportCode = Literal["NBA", "NFL", "NCAAF", "NCAAB", "MLB", "NHL"]
MarketType = Literal["spread", "total", "moneyline"]
ScraperType = Literal["boxscore", "odds", "boxscore_and_odds", "social", "pbp", "all"]


class TeamIdentity(BaseModel):
    league_code: SportCode
    name: str
    short_name: str | None = None
    abbreviation: str | None = None
    external_ref: str | None = None


class GameIdentification(BaseModel):
    league_code: SportCode
    season: int
    season_type: str = "regular"
    game_date: datetime
    home_team: TeamIdentity
    away_team: TeamIdentity
    source_game_key: str | None = None


class NormalizedTeamBoxscore(BaseModel):
    team: TeamIdentity
    is_home: bool
    points: int | None = None
    rebounds: int | None = None
    assists: int | None = None
    turnovers: int | None = None
    hits: int | None = None
    shots_on_goal: int | None = None
    penalty_minutes: int | None = None
    raw_stats: dict = Field(default_factory=dict)


class NormalizedPlayerBoxscore(BaseModel):
    player_id: str
    player_name: str
    team: TeamIdentity
    player_role: str | None = None  # "skater" or "goalie" for NHL; None for other sports
    position: str | None = None  # C, LW, RW, D, G for NHL
    sweater_number: int | None = None
    minutes: float | None = None
    points: int | None = None
    rebounds: int | None = None
    assists: int | None = None
    # Skater stats (NHL)
    shots_on_goal: int | None = None
    penalties: int | None = None
    goals: int | None = None
    plus_minus: int | None = None
    hits: int | None = None
    blocked_shots: int | None = None
    shifts: int | None = None
    giveaways: int | None = None
    takeaways: int | None = None
    faceoff_pct: float | None = None
    # Goalie stats (NHL)
    saves: int | None = None
    goals_against: int | None = None
    shots_against: int | None = None
    save_percentage: float | None = None
    raw_stats: dict = Field(default_factory=dict)


class NormalizedGame(BaseModel):
    identity: GameIdentification
    status: str = "completed"
    venue: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    team_boxscores: list[NormalizedTeamBoxscore] = Field(default_factory=list)
    player_boxscores: list[NormalizedPlayerBoxscore] = Field(default_factory=list)

    @field_validator("team_boxscores")
    @classmethod
    def ensure_team_alignment(cls, value: list[NormalizedTeamBoxscore]) -> list[NormalizedTeamBoxscore]:
        if not value:
            msg = "team_boxscores cannot be empty"
            raise ValueError(msg)
        return value


class NormalizedOddsSnapshot(BaseModel):
    league_code: SportCode
    book: str
    market_type: str  # Widened from MarketType literal to support prop market keys
    side: str | None = None
    line: float | None = None
    price: float | None = None
    observed_at: datetime
    home_team: TeamIdentity
    away_team: TeamIdentity
    game_date: datetime  # Date for matching (midnight ET as UTC)
    tip_time: datetime | None = None  # Actual start time (UTC)
    source_key: str | None = None
    is_closing_line: bool = True
    raw_payload: dict = Field(default_factory=dict)
    event_id: str | None = None  # Odds API event ID for prop fetching
    market_category: str = "mainline"  # mainline, player_prop, team_prop, alternate, period, game_prop
    player_name: str | None = None  # Player name for player props
    description: str | None = None  # Outcome description from API


def classify_market(market_key: str) -> str:
    """Classify a market key into a category.

    Returns:
        One of: mainline, player_prop, team_prop, alternate, period, game_prop
    """
    key = market_key.lower()
    if key in ("h2h", "spreads", "totals"):
        return "mainline"
    if key.startswith(("player_", "batter_", "pitcher_")):
        return "player_prop"
    if key.startswith("team_total"):
        return "team_prop"
    if key.startswith("alternate_"):
        return "alternate"
    # Period markets: h1, q1, etc.
    for suffix in ("_h1", "_h2", "_q1", "_q2", "_q3", "_q4", "_p1", "_p2", "_p3"):
        if key.endswith(suffix):
            return "period"
    return "game_prop"


class NormalizedPlay(BaseModel):
    """Single play-by-play event."""

    play_index: int
    quarter: int | None = None  # Period number; NHL uses periods instead of quarters.
    game_clock: str | None = None  # Remaining time in period; absolute timestamps go in raw_data["event_time"].
    play_type: str | None = None  # Supports league-specific enums (e.g., NHL eventTypeId).
    team_abbreviation: str | None = None
    player_id: str | None = None
    player_name: str | None = None
    description: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    raw_data: dict = Field(default_factory=dict)


class NormalizedPlayByPlay(BaseModel):
    """Play-by-play payload for a single game."""

    source_game_key: str
    plays: list[NormalizedPlay] = Field(default_factory=list)


class IngestionConfig(BaseModel):
    """Simplified scraper configuration.

    Data type toggles control what to scrape.
    Filters control which games to process.
    """

    league_code: SportCode
    season: int | None = None
    season_type: str = "regular"
    start_date: date | None = None
    end_date: date | None = None

    # Data type toggles (on/off)
    boxscores: bool = True  # Scrape boxscores (team + player stats)
    odds: bool = True  # Fetch odds from API
    social: bool = False  # Scrape X posts for games
    pbp: bool = False  # Scrape play-by-play
    batch_live_feed: bool = False  # Use live endpoints (cdn.nba.com) for PBP

    # Shared filters
    only_missing: bool = False  # Skip games that already have this data
    updated_before: date | None = None  # Only process if last updated before this date

    # Optional book filter for odds
    include_books: list[str] | None = None
