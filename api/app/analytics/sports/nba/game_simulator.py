"""NBA Monte Carlo game simulation.

Simulates individual NBA games at the possession level using
event probability distributions. Designed for high-volume use —
all calculations are stateless with no database calls.

Game flow:
    4 quarters (or more for ties), each with ~25 possessions per team.
    Each possession samples an event from the probability distribution.
    Points are awarded based on the event type.
    Tied games go to overtime periods until a winner is determined.
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.sports.nba.constants import (
    DEFAULT_EVENT_PROBS_SUFFIXED as _DEFAULT_PROBS,
)
from app.analytics.sports.nba.constants import (
    MAX_OVERTIMES as _MAX_OVERTIMES,
)
from app.analytics.sports.nba.constants import (
    OT_POSSESSIONS as _OT_POSSESSIONS,
)
from app.analytics.sports.nba.constants import (
    POSSESSION_EVENTS as EVENTS,
)
from app.analytics.sports.nba.constants import (
    QUARTER_POSSESSIONS as _QUARTER_POSSESSIONS,
)
from app.analytics.sports.nba.constants import (
    QUARTERS as _QUARTERS,
)

# Default free throw percentage when not supplied in context.
_DEFAULT_FT_PCT = 0.78


class NBAGameSimulator:
    """Simulate a single NBA game using possession-based probabilities."""

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete NBA game.

        Args:
            game_context: Must contain ``home_probabilities`` and
                ``away_probabilities`` dicts with possession event
                probability keys. Missing keys fall back to league-average
                defaults.
            rng: Optional ``random.Random`` instance for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            ``home_events``, ``away_events``, and ``periods_played``.
        """
        if rng is None:
            rng = random.Random()

        home_probs_raw = game_context.get("home_probabilities", {})
        away_probs_raw = game_context.get("away_probabilities", {})

        home_weights = _build_weights(home_probs_raw)
        away_weights = _build_weights(away_probs_raw)

        ft_pct_home = float(home_probs_raw.get("ft_pct", _DEFAULT_FT_PCT))
        ft_pct_away = float(away_probs_raw.get("ft_pct", _DEFAULT_FT_PCT))

        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        periods_played = 0

        # Regulation: 4 quarters
        for quarter in range(1, _QUARTERS + 1):
            periods_played = quarter
            h_pts, a_pts = _simulate_quarter(
                home_weights, away_weights, rng,
                home_events, away_events,
                ft_pct_home, ft_pct_away,
                _QUARTER_POSSESSIONS,
            )
            home_score += h_pts
            away_score += a_pts

        # Overtime periods
        ot = 0
        while home_score == away_score and ot < _MAX_OVERTIMES:
            h_pts, a_pts = _simulate_quarter(
                home_weights, away_weights, rng,
                home_events, away_events,
                ft_pct_home, ft_pct_away,
                _OT_POSSESSIONS,
            )
            home_score += h_pts
            away_score += a_pts
            ot += 1
            periods_played += 1

        winner = "home" if home_score > away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "home_events": home_events,
            "away_events": away_events,
            "periods_played": periods_played,
        }


# ---------------------------------------------------------------------------
# Event counter helper
# ---------------------------------------------------------------------------


def _new_event_counts() -> dict[str, int]:
    """Return a fresh event counter dict with all possession event keys zeroed."""
    return {e: 0 for e in EVENTS} | {"possessions_total": 0}


# ---------------------------------------------------------------------------
# Quarter simulation
# ---------------------------------------------------------------------------


def _simulate_quarter(
    home_weights: list[float],
    away_weights: list[float],
    rng: random.Random,
    home_events: dict[str, int],
    away_events: dict[str, int],
    ft_pct_home: float,
    ft_pct_away: float,
    possessions: int,
) -> tuple[int, int]:
    """Simulate one quarter (or OT period) returning (home_points, away_points)."""
    home_pts = 0
    away_pts = 0

    for _ in range(possessions):
        # Home possession
        home_pts += _simulate_possession(
            home_weights, rng, home_events, ft_pct_home,
        )
        # Away possession
        away_pts += _simulate_possession(
            away_weights, rng, away_events, ft_pct_away,
        )

    return home_pts, away_pts


def _simulate_possession(
    weights: list[float],
    rng: random.Random,
    events: dict[str, int],
    ft_pct: float,
) -> int:
    """Simulate a single possession, returning points scored."""
    event = rng.choices(EVENTS, weights=weights, k=1)[0]
    events[event] = events.get(event, 0) + 1
    events["possessions_total"] = events.get("possessions_total", 0) + 1

    if event == "two_pt_make":
        return 2
    elif event == "three_pt_make":
        return 3
    elif event == "free_throw_trip":
        # Simulate 2 individual free throws
        points = 0
        for _ in range(2):
            if rng.random() < ft_pct:
                points += 1
        return points
    else:
        # two_pt_miss, three_pt_miss, turnover
        return 0


# ---------------------------------------------------------------------------
# Weight construction
# ---------------------------------------------------------------------------


def _build_weights(probs: dict[str, float]) -> list[float]:
    """Convert a probability dict into ordered weights for ``EVENTS``.

    Maps ``*_probability`` keys to event order. ``two_pt_miss``
    absorbs the remaining probability mass after all named events.
    """
    two_make = max(probs.get("two_pt_make_probability", _DEFAULT_PROBS["two_pt_make_probability"]), 0.0)
    three_make = max(probs.get("three_pt_make_probability", _DEFAULT_PROBS["three_pt_make_probability"]), 0.0)
    three_miss = max(probs.get("three_pt_miss_probability", _DEFAULT_PROBS["three_pt_miss_probability"]), 0.0)
    ft_trip = max(probs.get("free_throw_trip_probability", _DEFAULT_PROBS["free_throw_trip_probability"]), 0.0)
    turnover = max(probs.get("turnover_probability", _DEFAULT_PROBS["turnover_probability"]), 0.0)

    named_total = two_make + three_make + three_miss + ft_trip + turnover
    two_miss = max(1.0 - named_total, 0.0)

    # Order matches EVENTS: two_pt_make, two_pt_miss, three_pt_make, three_pt_miss, free_throw_trip, turnover
    return [two_make, two_miss, three_make, three_miss, ft_trip, turnover]
