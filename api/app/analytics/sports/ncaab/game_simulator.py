"""NCAAB Monte Carlo game simulation.

Simulates individual NCAAB games at the possession level using a
four-factor probability model with offensive rebound mechanics.
Designed for high-volume use -- all calculations are stateless with
no database calls.

Supports two modes:

1. **Team-level** (``simulate_game``): single probability distribution
   per team for all possessions.
2. **Rotation-aware** (``simulate_game_with_lineups``): separate
   starter/bench unit weights with per-unit ORB% and FT%.  Each
   possession is randomly assigned to a unit based on ``starter_share``.

Game flow:
    2 halves (or more for ties), each with ~34 possessions per team.
    Each possession samples an event from the probability distribution.
    Missed shots can generate offensive rebounds for extra possessions.
    Free-throw trips simulate individual free throws at the team's
    FT percentage.
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.sports.ncaab.constants import (
    DEFAULT_EVENT_PROBS_SUFFIXED as _DEFAULT_PROBS,
)
from app.analytics.sports.ncaab.constants import (
    HALF_POSSESSIONS as _HALF_POSSESSIONS,
)
from app.analytics.sports.ncaab.constants import (
    HALVES as _HALVES,
)
from app.analytics.sports.ncaab.constants import (
    MAX_CONSECUTIVE_ORBS as _MAX_CONSECUTIVE_ORBS,
)
from app.analytics.sports.ncaab.constants import (
    MAX_OVERTIMES as _MAX_OVERTIMES,
)
from app.analytics.sports.ncaab.constants import (
    ORB_CHANCE as _ORB_CHANCE,
)
from app.analytics.sports.ncaab.constants import (
    OT_POSSESSIONS as _OT_POSSESSIONS,
)
from app.analytics.sports.ncaab.constants import (
    POSSESSION_EVENTS as _ALL_EVENTS,
)
from app.analytics.sports.ncaab.constants import (
    BASELINE_FT_PCT as _BASELINE_FT_PCT,
)

# Scorable events used for weighted sampling (excludes offensive_rebound).
_SAMPLE_EVENTS: list[str] = [
    "two_pt_make",
    "two_pt_miss",
    "three_pt_make",
    "three_pt_miss",
    "free_throw_trip",
    "turnover",
]


class NCAABGameSimulator:
    """Simulate a single NCAAB game using four-factor possession model."""

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete NCAAB game.

        Args:
            game_context: Must contain ``home_probabilities`` and
                ``away_probabilities`` dicts with event probability keys.
                Missing keys fall back to league-average defaults.
                Optional keys: ``orb_home``, ``orb_away`` (offensive
                rebound probability), ``ft_pct_home``, ``ft_pct_away``
                (free-throw percentage).
            rng: Optional ``random.Random`` instance for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            ``home_events``, ``away_events``, and ``periods_played``.
        """
        if rng is None:
            rng = random.Random()

        home_weights = _build_weights(game_context.get("home_probabilities", {}))
        away_weights = _build_weights(game_context.get("away_probabilities", {}))

        orb_home = float(game_context.get("orb_home", _ORB_CHANCE))
        orb_away = float(game_context.get("orb_away", _ORB_CHANCE))
        ft_pct_home = float(game_context.get("ft_pct_home", _BASELINE_FT_PCT))
        ft_pct_away = float(game_context.get("ft_pct_away", _BASELINE_FT_PCT))

        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        periods_played = 0

        # Regulation: 2 halves
        for _half in range(_HALVES):
            h, a = _simulate_half(
                home_weights,
                away_weights,
                rng,
                home_events,
                away_events,
                orb_home,
                orb_away,
                ft_pct_home,
                ft_pct_away,
                _HALF_POSSESSIONS,
            )
            home_score += h
            away_score += a
            periods_played += 1

        # Overtime
        ot = 0
        while home_score == away_score and ot < _MAX_OVERTIMES:
            h, a = _simulate_half(
                home_weights,
                away_weights,
                rng,
                home_events,
                away_events,
                orb_home,
                orb_away,
                ft_pct_home,
                ft_pct_away,
                _OT_POSSESSIONS,
            )
            home_score += h
            away_score += a
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

    def simulate_game_with_lineups(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Rotation-aware NCAAB simulation with starter/bench units.

        Each possession is randomly assigned to either the starter or
        bench unit.  Each unit has its own probability weights, FT%,
        and ORB%.

        Falls back to ``simulate_game`` if rotation keys are absent.
        """
        if "home_starter_weights" not in game_context:
            return self.simulate_game(game_context, rng)

        if rng is None:
            rng = random.Random()

        h_starter_w = game_context["home_starter_weights"]
        h_bench_w = game_context["home_bench_weights"]
        a_starter_w = game_context["away_starter_weights"]
        a_bench_w = game_context["away_bench_weights"]

        h_share = float(game_context.get("home_starter_share", 0.70))
        a_share = float(game_context.get("away_starter_share", 0.70))

        h_ft_s = float(game_context.get("home_ft_pct_starter", _BASELINE_FT_PCT))
        h_ft_b = float(game_context.get("home_ft_pct_bench", _BASELINE_FT_PCT))
        a_ft_s = float(game_context.get("away_ft_pct_starter", _BASELINE_FT_PCT))
        a_ft_b = float(game_context.get("away_ft_pct_bench", _BASELINE_FT_PCT))

        h_orb_s = float(game_context.get("home_orb_pct_starter", _ORB_CHANCE))
        h_orb_b = float(game_context.get("home_orb_pct_bench", _ORB_CHANCE))
        a_orb_s = float(game_context.get("away_orb_pct_starter", _ORB_CHANCE))
        a_orb_b = float(game_context.get("away_orb_pct_bench", _ORB_CHANCE))

        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        periods_played = 0

        for _half in range(_HALVES):
            h, a = _simulate_half_rotation(
                h_starter_w, h_bench_w, h_share,
                a_starter_w, a_bench_w, a_share,
                rng, home_events, away_events,
                h_ft_s, h_ft_b, a_ft_s, a_ft_b,
                h_orb_s, h_orb_b, a_orb_s, a_orb_b,
                _HALF_POSSESSIONS,
            )
            home_score += h
            away_score += a
            periods_played += 1

        # OT — starters play all OT minutes
        ot = 0
        while home_score == away_score and ot < _MAX_OVERTIMES:
            h, a = _simulate_half(
                h_starter_w, a_starter_w, rng,
                home_events, away_events,
                h_orb_s, a_orb_s,
                h_ft_s, a_ft_s,
                _OT_POSSESSIONS,
            )
            home_score += h
            away_score += a
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
# Half / period simulation
# ---------------------------------------------------------------------------


def _simulate_half(
    home_weights: list[float],
    away_weights: list[float],
    rng: random.Random,
    home_events: dict[str, int],
    away_events: dict[str, int],
    orb_home: float,
    orb_away: float,
    ft_pct_home: float,
    ft_pct_away: float,
    possessions_per_team: int,
) -> tuple[int, int]:
    """Simulate one half (or OT) for both teams, returning scores."""
    home_pts = _simulate_possessions(
        home_weights, rng, home_events, orb_home, ft_pct_home, possessions_per_team,
    )
    away_pts = _simulate_possessions(
        away_weights, rng, away_events, orb_away, ft_pct_away, possessions_per_team,
    )
    return home_pts, away_pts


def _simulate_half_rotation(
    h_starter_w: list[float],
    h_bench_w: list[float],
    h_share: float,
    a_starter_w: list[float],
    a_bench_w: list[float],
    a_share: float,
    rng: random.Random,
    home_events: dict[str, int],
    away_events: dict[str, int],
    h_ft_s: float,
    h_ft_b: float,
    a_ft_s: float,
    a_ft_b: float,
    h_orb_s: float,
    h_orb_b: float,
    a_orb_s: float,
    a_orb_b: float,
    possessions_per_team: int,
) -> tuple[int, int]:
    """Simulate one half with rotation — each possession randomly
    assigned to starter or bench unit."""
    home_pts = 0
    away_pts = 0

    for _ in range(possessions_per_team):
        # Home possession
        if rng.random() < h_share:
            home_pts += _resolve_possession(
                h_starter_w, rng, home_events, h_orb_s, h_ft_s, 0,
            )
        else:
            home_pts += _resolve_possession(
                h_bench_w, rng, home_events, h_orb_b, h_ft_b, 0,
            )

        # Away possession
        if rng.random() < a_share:
            away_pts += _resolve_possession(
                a_starter_w, rng, away_events, a_orb_s, a_ft_s, 0,
            )
        else:
            away_pts += _resolve_possession(
                a_bench_w, rng, away_events, a_orb_b, a_ft_b, 0,
            )

    return home_pts, away_pts


def _simulate_possessions(
    weights: list[float],
    rng: random.Random,
    events: dict[str, int],
    orb_pct: float,
    ft_pct: float,
    num_possessions: int,
) -> int:
    """Simulate a set of possessions for one team, returning points scored."""
    points = 0

    for _ in range(num_possessions):
        pts = _resolve_possession(weights, rng, events, orb_pct, ft_pct, 0)
        points += pts

    return points


def _resolve_possession(
    weights: list[float],
    rng: random.Random,
    events: dict[str, int],
    orb_pct: float,
    ft_pct: float,
    consecutive_orbs: int,
) -> int:
    """Resolve a single possession, handling ORB recursion.

    Returns points scored on this possession (including any ORB
    follow-up possessions).
    """
    event = rng.choices(_SAMPLE_EVENTS, weights=weights, k=1)[0]

    events[event] = events.get(event, 0) + 1
    events["possessions_total"] = events.get("possessions_total", 0) + 1

    if event == "two_pt_make":
        return 2

    if event == "three_pt_make":
        return 3

    if event == "free_throw_trip":
        return _simulate_free_throws(rng, ft_pct)

    if event == "turnover":
        return 0

    # Miss (two_pt_miss or three_pt_miss): check for offensive rebound
    if consecutive_orbs < _MAX_CONSECUTIVE_ORBS and rng.random() < orb_pct:
        events["offensive_rebounds"] = events.get("offensive_rebounds", 0) + 1
        return _resolve_possession(
            weights, rng, events, orb_pct, ft_pct, consecutive_orbs + 1,
        )

    return 0


def _simulate_free_throws(rng: random.Random, ft_pct: float) -> int:
    """Simulate a 2-shot free-throw trip, returning points scored."""
    points = 0
    for _ in range(2):
        if rng.random() < ft_pct:
            points += 1
    return points


# ---------------------------------------------------------------------------
# Event counter helper
# ---------------------------------------------------------------------------


def _new_event_counts() -> dict[str, int]:
    """Return a fresh event counter dict with all event keys zeroed."""
    counts: dict[str, int] = {e: 0 for e in _SAMPLE_EVENTS}
    counts["possessions_total"] = 0
    counts["offensive_rebounds"] = 0
    return counts


# ---------------------------------------------------------------------------
# Weight construction
# ---------------------------------------------------------------------------


def _build_weights(probs: dict[str, float]) -> list[float]:
    """Convert a probability dict into ordered weights for ``_SAMPLE_EVENTS``.

    Maps ``*_probability`` keys to event order. ``two_pt_miss`` absorbs
    the remaining probability mass after all other named events.
    """
    two_make = max(
        probs.get("two_pt_make_probability", _DEFAULT_PROBS["two_pt_make_probability"]),
        0.0,
    )
    three_make = max(
        probs.get("three_pt_make_probability", _DEFAULT_PROBS["three_pt_make_probability"]),
        0.0,
    )
    three_miss = max(
        probs.get("three_pt_miss_probability", _DEFAULT_PROBS["three_pt_miss_probability"]),
        0.0,
    )
    ft = max(
        probs.get("free_throw_trip_probability", _DEFAULT_PROBS["free_throw_trip_probability"]),
        0.0,
    )
    tov = max(
        probs.get("turnover_probability", _DEFAULT_PROBS["turnover_probability"]),
        0.0,
    )

    named_total = two_make + three_make + three_miss + ft + tov
    two_miss = max(1.0 - named_total, 0.0)

    # Order matches _SAMPLE_EVENTS:
    # two_pt_make, two_pt_miss, three_pt_make, three_pt_miss, free_throw_trip, turnover
    return [two_make, two_miss, three_make, three_miss, ft, tov]
