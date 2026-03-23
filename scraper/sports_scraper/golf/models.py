"""Pydantic models for DataGolf API responses.

These models represent the parsed response shapes from the DataGolf API.
They are used by the client to validate and type API responses before
persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class DGTournament:
    """Tournament from the DataGolf schedule API."""

    event_id: str  # e.g. "026" or combined "pga-026"
    event_name: str
    course: str
    course_key: str  # DataGolf course identifier
    start_date: date
    end_date: date | None
    tour: str  # "pga", "euro", "kft", "alt", "opp"
    status: str | None = None  # "completed", "in_progress", "scheduled"
    purse: float | None = None
    currency: str = "USD"
    latitude: float | None = None
    longitude: float | None = None
    country: str | None = None
    season: int | None = None


@dataclass(frozen=True)
class DGPlayer:
    """Player from the DataGolf player list API."""

    dg_id: int
    player_name: str
    country: str | None = None
    country_code: str | None = None
    amateur: bool = False
    # DFS site IDs for lineup matching
    dk_id: int | None = None
    fd_id: int | None = None
    yahoo_id: int | None = None


@dataclass(frozen=True)
class DGFieldEntry:
    """Single player entry in a tournament field."""

    dg_id: int
    player_name: str
    country: str | None = None
    dk_salary: int | None = None
    fd_salary: int | None = None
    early_late: str | None = None  # "early" or "late" for split tee times
    tee_time: str | None = None
    course: str | None = None  # For multi-course events
    r1_teetime: str | None = None
    r2_teetime: str | None = None


@dataclass(frozen=True)
class DGSkillRating:
    """Player skill rating from the DataGolf skill-ratings API."""

    dg_id: int
    player_name: str
    # Strokes gained components
    sg_total: float | None = None
    sg_ott: float | None = None  # Off the tee
    sg_app: float | None = None  # Approach
    sg_arg: float | None = None  # Around the green
    sg_putt: float | None = None  # Putting
    # Metadata
    driving_dist: float | None = None
    driving_acc: float | None = None
    sample_size: int | None = None


@dataclass(frozen=True)
class DGRanking:
    """Player ranking from the DataGolf rankings API."""

    dg_id: int
    player_name: str
    rank: int
    datagolf_rank: int | None = None
    owgr: int | None = None  # Official world golf ranking
    am: bool = False


@dataclass(frozen=True)
class DGPreTournamentPred:
    """Pre-tournament prediction for a single player."""

    dg_id: int
    player_name: str
    win_prob: float | None = None
    top_5_prob: float | None = None
    top_10_prob: float | None = None
    top_20_prob: float | None = None
    make_cut_prob: float | None = None


@dataclass(frozen=True)
class DGLeaderboardEntry:
    """Live or final leaderboard entry from DataGolf."""

    dg_id: int
    player_name: str
    position: int | None = None
    total_score: int | None = None  # Total strokes relative to par
    today_score: int | None = None  # Today's round relative to par
    thru: int | None = None  # Holes completed in current round (0-18)
    total_strokes: int | None = None
    # Round scores
    r1: int | None = None
    r2: int | None = None
    r3: int | None = None
    r4: int | None = None
    # Strokes gained (live)
    sg_total: float | None = None
    sg_ott: float | None = None
    sg_app: float | None = None
    sg_arg: float | None = None
    sg_putt: float | None = None
    # Status
    status: str = "active"  # "active", "cut", "wd", "dq"
    # Live predictions
    win_prob: float | None = None
    top_5_prob: float | None = None
    top_10_prob: float | None = None
    make_cut_prob: float | None = None


@dataclass(frozen=True)
class DGOddsOutright:
    """Outright odds for a player in a tournament."""

    dg_id: int
    player_name: str
    book: str  # "draftkings", "fanduel", etc.
    market: str  # "win", "top_5", "top_10", "make_cut", "mc"
    odds: float  # American odds
    implied_prob: float | None = None
    # DataGolf model fair value for comparison
    dg_prob: float | None = None


@dataclass(frozen=True)
class DGMatchup:
    """Head-to-head or 3-ball matchup odds."""

    matchup_type: str  # "2_balls" or "3_balls"
    book: str
    # Players in the matchup
    players: list[dict] = field(default_factory=list)
    # Each dict: {"dg_id": int, "player_name": str, "odds": float, "dg_prob": float}


@dataclass(frozen=True)
class DGDFSProjection:
    """DFS projection for a player on a specific site/slate."""

    dg_id: int
    player_name: str
    site: str  # "draftkings", "fanduel", "yahoo"
    salary: int
    projected_points: float | None = None
    projected_ownership: float | None = None


@dataclass(frozen=True)
class DGRound:
    """Historical or live round data for a player."""

    dg_id: int
    player_name: str
    event_id: str
    round_num: int
    course: str | None = None
    score: int | None = None  # Relative to par
    strokes: int | None = None  # Total strokes
    sg_total: float | None = None
    sg_ott: float | None = None
    sg_app: float | None = None
    sg_arg: float | None = None
    sg_putt: float | None = None
    # Traditional stats
    driving_dist: float | None = None
    driving_acc: float | None = None
    gir: float | None = None
    scrambling: float | None = None
    prox: float | None = None  # Proximity to hole (feet)
    putts_per_round: float | None = None


@dataclass(frozen=True)
class DGEventResult:
    """Historical event finish for a player."""

    dg_id: int
    player_name: str
    event_id: str
    event_name: str
    finish_position: int | None = None
    score: int | None = None
    earnings: float | None = None
    fedex_pts: float | None = None
    season: int | None = None
