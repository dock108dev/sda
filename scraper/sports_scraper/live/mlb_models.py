"""Data models for MLB live feed processing.

Contains dataclasses representing games and boxscores from the MLB Stats API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..models import TeamIdentity


@dataclass(frozen=True)
class MLBLiveGame:
    """Represents a game from the MLB schedule API."""

    game_pk: int
    game_date: datetime
    status: str
    home_team: TeamIdentity
    away_team: TeamIdentity
    home_score: int | None
    away_score: int | None
    venue: str | None = None
    weather: dict | None = None


@dataclass
class MLBBoxscore:
    """Represents boxscore data from the MLB Stats API.

    Contains team and player stats parsed from the boxscore endpoint.
    """

    game_pk: int
    status: str
    home_team: TeamIdentity
    away_team: TeamIdentity
    home_score: int
    away_score: int
    game_date: datetime | None = None  # Not available from the boxscore endpoint
    team_boxscores: list = field(default_factory=list)  # List of NormalizedTeamBoxscore
    player_boxscores: list = field(default_factory=list)  # List of NormalizedPlayerBoxscore
