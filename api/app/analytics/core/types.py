"""Common analytics data structures used across all sports.

These types define the shared vocabulary for analytics results. Sport-specific
modules extend them with additional fields as needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerProfile:
    """Aggregated analytical profile for a single player.

    Populated by sport-specific metrics modules. The ``metrics`` dict
    holds computed values whose keys are sport-dependent (e.g.,
    ``swing_rate``, ``contact_rate`` for MLB).
    """

    player_id: str
    sport: str
    name: str = ""
    team_id: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamProfile:
    """Aggregated analytical profile for a team.

    Holds both team-level computed metrics and optional roster-level
    summaries.
    """

    team_id: str
    sport: str
    name: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    roster_summary: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MatchupProfile:
    """Analysis of a head-to-head matchup between two entities.

    Entities can be teams, players, or any comparable units depending
    on the sport module's implementation.
    """

    entity_a_id: str
    entity_b_id: str
    sport: str
    comparison: dict[str, Any] = field(default_factory=dict)
    advantages: dict[str, str] = field(default_factory=dict)
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass
class SimulationResult:
    """Output from a simulation run.

    ``outcomes`` holds the raw distribution; ``summary`` holds
    aggregated statistics (mean, median, percentiles, etc.).
    """

    sport: str
    iterations: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
