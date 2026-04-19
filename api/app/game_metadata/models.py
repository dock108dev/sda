"""Pydantic models for game metadata."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TeamRatings(BaseModel):
    model_config = _ALIAS_CFG

    team_id: str
    conference: str
    elo: float
    kenpom_adj_eff: float | None = None
    projected_seed: int | None = None


class StandingsEntry(BaseModel):
    model_config = _ALIAS_CFG

    team_id: str
    conference_rank: int
    wins: int
    losses: int


class GameContext(BaseModel):
    model_config = _ALIAS_CFG

    game_id: str
    home_team: str
    away_team: str
    league: str
    start_time: datetime
    rivalry: bool = False
    projected_spread: float | None = None
    has_big_name_players: bool = False
    coach_vs_former_team: bool = False
    playoff_implications: bool = False
    national_broadcast: bool = False
    projected_total: float | None = None
