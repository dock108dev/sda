"""Types and constants for moment generation.

This module contains configuration values, enums, and dataclasses used
throughout the moment generation process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# =============================================================================
# MOMENT COMPRESSION CONFIGURATION
# =============================================================================
# These values are tunable without code changes.

# Soft cap: prefer closing at this point
# With 30 plays, moments will typically contain 10-15 possessions
SOFT_CAP_PLAYS = 30

# Absolute cap: must close (safety valve, should be rare)
# Allows for large moments that cover significant game stretches
ABSOLUTE_MAX_PLAYS = 50

# Minimum plays before soft boundaries take effect
# Prevents creating tiny moments; with 15 plays min, moments cover 5-8 possessions
MIN_PLAYS_BEFORE_SOFT_CLOSE = 15

# Maximum explicitly narrated plays per moment
# Increased to allow richer narratives covering more key plays
MAX_EXPLICIT_PLAYS_PER_MOMENT = 5

# Target: prefer <=3 explicit plays per moment for balanced narratives
PREFERRED_EXPLICIT_PLAYS = 3


class BoundaryType(str, Enum):
    """Classification of boundary decision type."""

    HARD = "HARD"  # Non-negotiable, must close
    SOFT = "SOFT"  # Prefer closing, but can continue if flow demands


class BoundaryReason(str, Enum):
    """Specific reason for moment boundary."""

    # Hard boundaries (always close)
    PERIOD_BOUNDARY = "PERIOD_BOUNDARY"
    LEAD_CHANGE = "LEAD_CHANGE"
    FIRST_MEANINGFUL_LEAD = "FIRST_MEANINGFUL_LEAD"
    EXPLICIT_PLAY_OVERFLOW = "EXPLICIT_PLAY_OVERFLOW"
    ABSOLUTE_MAX_PLAYS = "ABSOLUTE_MAX_PLAYS"

    # Soft boundaries (prefer closing)
    SOFT_CAP_REACHED = "SOFT_CAP_REACHED"
    SCORING_PLAY = "SCORING_PLAY"
    POSSESSION_CHANGE = "POSSESSION_CHANGE"
    STOPPAGE = "STOPPAGE"
    SECOND_EXPLICIT_PLAY = "SECOND_EXPLICIT_PLAY"

    # End of input
    END_OF_INPUT = "END_OF_INPUT"

    @property
    def is_hard(self) -> bool:
        """Check if this is a hard (non-negotiable) boundary."""
        return self in {
            BoundaryReason.PERIOD_BOUNDARY,
            BoundaryReason.LEAD_CHANGE,
            BoundaryReason.FIRST_MEANINGFUL_LEAD,
            BoundaryReason.EXPLICIT_PLAY_OVERFLOW,
            BoundaryReason.ABSOLUTE_MAX_PLAYS,
        }


@dataclass
class CompressionMetrics:
    """Instrumentation metrics for moment compression.

    These metrics track distribution characteristics for validation.
    """

    total_moments: int = 0
    total_plays: int = 0
    plays_per_moment: list[int] = field(default_factory=list)
    explicit_plays_per_moment: list[int] = field(default_factory=list)
    boundary_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def pct_moments_under_soft_cap(self) -> float:
        """Percentage of moments with <= SOFT_CAP_PLAYS plays."""
        if not self.plays_per_moment:
            return 0.0
        under = sum(1 for p in self.plays_per_moment if p <= SOFT_CAP_PLAYS)
        return (under / len(self.plays_per_moment)) * 100

    @property
    def pct_moments_single_explicit(self) -> float:
        """Percentage of moments with <= 1 explicitly narrated play."""
        if not self.explicit_plays_per_moment:
            return 0.0
        single = sum(1 for e in self.explicit_plays_per_moment if e <= 1)
        return (single / len(self.explicit_plays_per_moment)) * 100

    @property
    def median_plays_per_moment(self) -> float:
        """Median plays per moment."""
        if not self.plays_per_moment:
            return 0.0
        sorted_plays = sorted(self.plays_per_moment)
        n = len(sorted_plays)
        if n % 2 == 0:
            return (sorted_plays[n // 2 - 1] + sorted_plays[n // 2]) / 2
        return float(sorted_plays[n // 2])

    @property
    def max_plays_observed(self) -> int:
        """Maximum plays in any moment."""
        return max(self.plays_per_moment) if self.plays_per_moment else 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "total_moments": self.total_moments,
            "total_plays": self.total_plays,
            "pct_moments_under_soft_cap": round(self.pct_moments_under_soft_cap, 1),
            "pct_moments_single_explicit": round(self.pct_moments_single_explicit, 1),
            "median_plays_per_moment": round(self.median_plays_per_moment, 1),
            "max_plays_observed": self.max_plays_observed,
            "avg_plays_per_moment": round(
                sum(self.plays_per_moment) / len(self.plays_per_moment), 1
            ) if self.plays_per_moment else 0,
            "boundary_reasons": self.boundary_reasons,
        }


# Play types that indicate stoppages (timeouts, reviews, etc.)
STOPPAGE_PLAY_TYPES = frozenset([
    "timeout",
    "full_timeout",
    "official_timeout",
    "tv_timeout",
    "20_second_timeout",
    "review",
    "instant_replay",
    "delay_of_game",
    "ejection",
])

# Play types that indicate possession change / turnover
TURNOVER_PLAY_TYPES = frozenset([
    "turnover",
    "steal",
    "lost_ball",
    "bad_pass",
    "out_of_bounds",
    "offensive_foul",
    "traveling",
    "travel",
    "double_dribble",
    "kicked_ball",
])

# Play types that are notable and should be narrated (non-scoring)
NOTABLE_PLAY_TYPES = frozenset([
    # Defensive plays
    "block",
    "blocked_shot",
    "steal",
    # Turnovers
    "turnover",
    "offensive_foul",
    # Rebounds (contested action)
    "offensive_rebound",
    "defensive_rebound",
    # Fast breaks / assists
    "assist",
    "fast_break",
    # Fouls
    "foul",
    "personal_foul",
    "shooting_foul",
    "technical_foul",
    "flagrant_foul",
    # Other notable events
    "jump_ball",
    "jumpball",
    "violation",
])
