"""NHL Monte Carlo game simulation.

Simulates individual NHL games at the shot-attempt level using
probability distributions. Designed for high-volume use -- all
calculations are stateless with no database calls.

Supports two modes:

1. **Team-level** (``simulate_game``): single probability distribution
   per team for all shot attempts.
2. **Rotation-aware** (``simulate_game_with_lineups``): separate
   top-line/depth unit weights. Each shot is randomly assigned to
   a unit based on ``starter_share``. OT uses top-line only.

Game flow:
    3 regulation periods, each with ~SHOTS_PER_PERIOD attempts per team.
    Each shot attempt is sampled from SHOT_EVENTS weighted by team's
    probabilities. Goals increment score.
    If tied after regulation: sudden-death OT (OT_SHOTS per team).
    If still tied: shootout simulation (alternating rounds).
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.sports.nhl.constants import (
    DEFAULT_EVENT_PROBS_SUFFIXED as _DEFAULT_PROBS,
)
from app.analytics.sports.nhl.constants import (
    MAX_OVERTIMES as _MAX_OVERTIMES,
)
from app.analytics.sports.nhl.constants import (
    OT_SHOTS as _OT_SHOTS,
)
from app.analytics.sports.nhl.constants import (
    PERIODS as _PERIODS,
)
from app.analytics.sports.nhl.constants import (
    SHOOTOUT_GOAL_PROB as _SHOOTOUT_GOAL_PROB,
)
from app.analytics.sports.nhl.constants import (
    SHOOTOUT_ROUNDS as _SHOOTOUT_ROUNDS,
)
from app.analytics.sports.nhl.constants import (
    SHOT_EVENTS as EVENTS,
)
from app.analytics.sports.nhl.constants import (
    SHOTS_PER_PERIOD as _SHOTS_PER_PERIOD,
)


class NHLGameSimulator:
    """Simulate a single NHL game using shot-based probabilities."""

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete NHL game.

        Args:
            game_context: Must contain ``home_probabilities`` and
                ``away_probabilities`` dicts with event probability keys.
                Missing keys fall back to league-average defaults.
            rng: Optional ``random.Random`` instance for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            ``home_events``, ``away_events``, ``periods_played``,
            and ``went_to_shootout``.
        """
        if rng is None:
            rng = random.Random()

        home_weights = _build_weights(game_context.get("home_probabilities", {}))
        away_weights = _build_weights(game_context.get("away_probabilities", {}))

        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        periods_played = 0
        went_to_shootout = False

        # Regulation: 3 periods
        for _period in range(1, _PERIODS + 1):
            periods_played = _period
            h_goals, a_goals = _simulate_period(
                home_weights, away_weights, rng, home_events, away_events,
            )
            home_score += h_goals
            away_score += a_goals

        # Overtime (if tied after regulation)
        if home_score == away_score:
            periods_played += 1
            for _ot in range(_MAX_OVERTIMES):
                winner = _simulate_ot(
                    home_weights, away_weights, rng, home_events, away_events,
                )
                if winner == "home":
                    home_score += 1
                    break
                elif winner == "away":
                    away_score += 1
                    break

        # Shootout (if still tied after OT)
        if home_score == away_score:
            went_to_shootout = True
            home_goal_prob = game_context.get("home_probabilities", {}).get(
                "goal_probability", _DEFAULT_PROBS["goal_probability"],
            )
            away_goal_prob = game_context.get("away_probabilities", {}).get(
                "goal_probability", _DEFAULT_PROBS["goal_probability"],
            )
            # Shootout goal probs are typically higher than even-strength;
            # use a blend of team shooting and league shootout average.
            home_so_prob = (home_goal_prob + _SHOOTOUT_GOAL_PROB) / 2
            away_so_prob = (away_goal_prob + _SHOOTOUT_GOAL_PROB) / 2

            so_winner = _simulate_shootout(rng, home_so_prob, away_so_prob)
            if so_winner == "home":
                home_score += 1
            else:
                away_score += 1

        winner = "home" if home_score > away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "home_events": home_events,
            "away_events": away_events,
            "periods_played": periods_played,
            "went_to_shootout": went_to_shootout,
        }

    def simulate_game_with_lineups(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Rotation-aware NHL simulation with top-line/depth units.

        Each shot attempt is randomly assigned to top-line or depth
        unit based on ``*_starter_share``. OT uses top-line only.
        Shootout uses team-level goal probability.

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

        h_share = float(game_context.get("home_starter_share", 0.65))
        a_share = float(game_context.get("away_starter_share", 0.65))

        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        periods_played = 0
        went_to_shootout = False

        # Regulation: 3 periods with rotation
        for _period in range(1, _PERIODS + 1):
            periods_played = _period
            h_goals, a_goals = _simulate_period_rotation(
                h_starter_w, h_bench_w, h_share,
                a_starter_w, a_bench_w, a_share,
                rng, home_events, away_events,
            )
            home_score += h_goals
            away_score += a_goals

        # OT — top-line only
        if home_score == away_score:
            periods_played += 1
            for _ot in range(_MAX_OVERTIMES):
                winner = _simulate_ot(
                    h_starter_w, a_starter_w, rng, home_events, away_events,
                )
                if winner == "home":
                    home_score += 1
                    break
                elif winner == "away":
                    away_score += 1
                    break

        # Shootout (team-level)
        if home_score == away_score:
            went_to_shootout = True
            h_goal_prob = h_starter_w[0]  # goal weight from starter unit
            a_goal_prob = a_starter_w[0]
            home_so_prob = (h_goal_prob + _SHOOTOUT_GOAL_PROB) / 2
            away_so_prob = (a_goal_prob + _SHOOTOUT_GOAL_PROB) / 2

            so_winner = _simulate_shootout(rng, home_so_prob, away_so_prob)
            if so_winner == "home":
                home_score += 1
            else:
                away_score += 1

        winner = "home" if home_score > away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "home_events": home_events,
            "away_events": away_events,
            "periods_played": periods_played,
            "went_to_shootout": went_to_shootout,
        }


# ---------------------------------------------------------------------------
# Event counter helper
# ---------------------------------------------------------------------------


def _new_event_counts() -> dict[str, int]:
    """Return a fresh event counter dict with all shot event keys zeroed."""
    return {e: 0 for e in EVENTS} | {"shots_total": 0}


# ---------------------------------------------------------------------------
# Period / OT / Shootout simulation
# ---------------------------------------------------------------------------


def _simulate_period(
    home_weights: list[float],
    away_weights: list[float],
    rng: random.Random,
    home_events: dict[str, int],
    away_events: dict[str, int],
) -> tuple[int, int]:
    """Simulate one regulation period, returning (home_goals, away_goals)."""
    home_goals = 0
    away_goals = 0

    for _shot in range(_SHOTS_PER_PERIOD):
        # Home shot attempt
        event = rng.choices(EVENTS, weights=home_weights, k=1)[0]
        home_events[event] += 1
        home_events["shots_total"] += 1
        if event == "goal":
            home_goals += 1

        # Away shot attempt
        event = rng.choices(EVENTS, weights=away_weights, k=1)[0]
        away_events[event] += 1
        away_events["shots_total"] += 1
        if event == "goal":
            away_goals += 1

    return home_goals, away_goals


def _simulate_period_rotation(
    h_starter_w: list[float],
    h_bench_w: list[float],
    h_share: float,
    a_starter_w: list[float],
    a_bench_w: list[float],
    a_share: float,
    rng: random.Random,
    home_events: dict[str, int],
    away_events: dict[str, int],
) -> tuple[int, int]:
    """Simulate one period with rotation — each shot assigned to a unit."""
    home_goals = 0
    away_goals = 0

    for _shot in range(_SHOTS_PER_PERIOD):
        # Home shot
        w = h_starter_w if rng.random() < h_share else h_bench_w
        event = rng.choices(EVENTS, weights=w, k=1)[0]
        home_events[event] += 1
        home_events["shots_total"] += 1
        if event == "goal":
            home_goals += 1

        # Away shot
        w = a_starter_w if rng.random() < a_share else a_bench_w
        event = rng.choices(EVENTS, weights=w, k=1)[0]
        away_events[event] += 1
        away_events["shots_total"] += 1
        if event == "goal":
            away_goals += 1

    return home_goals, away_goals


def _simulate_ot(
    home_weights: list[float],
    away_weights: list[float],
    rng: random.Random,
    home_events: dict[str, int],
    away_events: dict[str, int],
) -> str | None:
    """Simulate sudden-death overtime, returning winner or None."""
    for _shot in range(_OT_SHOTS):
        # Home shot attempt
        event = rng.choices(EVENTS, weights=home_weights, k=1)[0]
        home_events[event] += 1
        home_events["shots_total"] += 1
        if event == "goal":
            return "home"

        # Away shot attempt
        event = rng.choices(EVENTS, weights=away_weights, k=1)[0]
        away_events[event] += 1
        away_events["shots_total"] += 1
        if event == "goal":
            return "away"

    return None


def _simulate_shootout(
    rng: random.Random,
    home_goal_prob: float,
    away_goal_prob: float,
) -> str:
    """Simulate a shootout, returning 'home' or 'away'."""
    home_goals = 0
    away_goals = 0

    # Standard rounds
    for _round in range(_SHOOTOUT_ROUNDS):
        if rng.random() < home_goal_prob:
            home_goals += 1
        if rng.random() < away_goal_prob:
            away_goals += 1

        rounds_remaining = _SHOOTOUT_ROUNDS - _round - 1
        # Check if a team has clinched (can't be caught)
        if home_goals > away_goals + rounds_remaining:
            return "home"
        if away_goals > home_goals + rounds_remaining:
            return "away"

    # If tied after standard rounds, sudden-death rounds
    max_sudden_death = 20  # safety cap
    for _sd in range(max_sudden_death):
        home_scored = rng.random() < home_goal_prob
        away_scored = rng.random() < away_goal_prob
        if home_scored and not away_scored:
            return "home"
        if away_scored and not home_scored:
            return "away"
        # Both scored or neither scored: continue

    # Fallback (extremely unlikely)
    return "home"


# ---------------------------------------------------------------------------
# Weight construction
# ---------------------------------------------------------------------------


def _build_weights(probs: dict[str, float]) -> list[float]:
    """Convert a probability dict into ordered weights for ``EVENTS``.

    Maps ``*_probability`` keys to event order. ``save`` absorbs the
    remaining probability mass after all named events.
    """
    goal = max(probs.get("goal_probability", _DEFAULT_PROBS["goal_probability"]), 0.0)
    blocked = max(
        probs.get("blocked_shot_probability", _DEFAULT_PROBS["blocked_shot_probability"]),
        0.0,
    )
    missed = max(
        probs.get("missed_shot_probability", _DEFAULT_PROBS["missed_shot_probability"]),
        0.0,
    )

    named_total = goal + blocked + missed
    save_prob = max(1.0 - named_total, 0.0)

    # Order matches EVENTS: goal, save, blocked_shot, missed_shot
    return [goal, save_prob, blocked, missed]
