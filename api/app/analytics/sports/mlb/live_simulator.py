"""MLB live game simulator.

Simulates remaining innings from a partial game state using the same
plate-appearance model as ``game_simulator.py``. Designed for real-time
use during live games — all calculations are stateless with no DB calls.

Game state input example::

    {
        "inning": 6,
        "half": "top",       # "top" or "bottom"
        "outs": 1,
        "bases": {"first": True, "second": False, "third": False},
        "score": {"home": 3, "away": 2},
        "home_probabilities": {...},
        "away_probabilities": {...},
    }
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.sports.mlb.game_simulator import (
    EVENTS,
    _advance_double,
    _advance_home_run,
    _advance_single,
    _advance_triple,
    _advance_walk,
    _build_weights,
    _MAX_EXTRA_INNINGS,
)


class MLBLiveSimulator:
    """Simulate the remainder of an MLB game from a partial state."""

    def simulate_from_state(
        self,
        game_state: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one game from the current state to completion.

        Args:
            game_state: Current game state including inning, half,
                outs, bases, score, and probability distributions.
            rng: Optional RNG for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, and ``winner``.
        """
        if rng is None:
            rng = random.Random()

        home_probs = _build_weights(game_state.get("home_probabilities", {}))
        away_probs = _build_weights(game_state.get("away_probabilities", {}))

        score = game_state.get("score", {})
        home_score = score.get("home", 0)
        away_score = score.get("away", 0)

        current_inning = game_state.get("inning", 1)
        half = game_state.get("half", "top")
        current_outs = game_state.get("outs", 0)

        bases_state = game_state.get("bases", {})
        current_bases = [
            bool(bases_state.get("first", False)),
            bool(bases_state.get("second", False)),
            bool(bases_state.get("third", False)),
        ]

        # Finish the current half-inning if mid-play
        if half == "top":
            # Finish top of current inning
            away_score += _simulate_partial_half_inning(
                away_probs, rng, current_outs, current_bases,
            )
            # Bottom of current inning
            if not (current_inning >= 9 and home_score > away_score):
                home_score += _simulate_full_half_inning(home_probs, rng)
                # Walk-off check
                if current_inning >= 9 and home_score > away_score:
                    return _result(home_score, away_score)

            # Remaining full innings
            for inning in range(current_inning + 1, 10):
                away_score += _simulate_full_half_inning(away_probs, rng)
                if inning == 9 and home_score > away_score:
                    break
                home_score += _simulate_full_half_inning(home_probs, rng)
                if inning == 9 and home_score > away_score:
                    break

        else:  # half == "bottom"
            # Finish bottom of current inning
            home_score += _simulate_partial_half_inning(
                home_probs, rng, current_outs, current_bases,
            )
            # Walk-off check
            if current_inning >= 9 and home_score > away_score:
                return _result(home_score, away_score)

            # Remaining full innings
            for inning in range(current_inning + 1, 10):
                away_score += _simulate_full_half_inning(away_probs, rng)
                if inning == 9 and home_score > away_score:
                    break
                home_score += _simulate_full_half_inning(home_probs, rng)
                if inning == 9 and home_score > away_score:
                    break

        # Extra innings
        extra = 0
        while home_score == away_score and extra < _MAX_EXTRA_INNINGS:
            away_score += _simulate_full_half_inning(away_probs, rng)
            home_score += _simulate_full_half_inning(home_probs, rng)
            extra += 1

        return _result(home_score, away_score)


def _simulate_partial_half_inning(
    weights: list[float],
    rng: random.Random,
    outs: int,
    bases: list[bool],
) -> int:
    """Simulate the remainder of a half-inning from given outs/bases."""
    runs = 0
    while outs < 3:
        event = rng.choices(EVENTS, weights=weights, k=1)[0]

        if event in ("strikeout", "out"):
            outs += 1
        elif event == "walk":
            runs += _advance_walk(bases)
        elif event == "single":
            runs += _advance_single(bases)
        elif event == "double":
            runs += _advance_double(bases)
        elif event == "triple":
            runs += _advance_triple(bases)
        elif event == "home_run":
            runs += _advance_home_run(bases)

    return runs


def _simulate_full_half_inning(
    weights: list[float],
    rng: random.Random,
) -> int:
    """Simulate a complete half-inning (0 outs, empty bases)."""
    return _simulate_partial_half_inning(weights, rng, 0, [False, False, False])


def _result(home_score: int, away_score: int) -> dict[str, Any]:
    return {
        "home_score": home_score,
        "away_score": away_score,
        "winner": "home" if home_score >= away_score else "away",
    }
