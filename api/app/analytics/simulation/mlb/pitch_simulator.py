"""MLB pitch-level game simulation.

Simulates individual pitches within each plate appearance instead of
sampling PA outcomes directly. This produces more realistic count
distributions, walk/strikeout rates, and allows pitch-level analytics.

Flow per PA:
    1. Predict pitch outcome (ball / strike / foul / in_play)
    2. Update count
    3. If in_play: predict batted ball outcome
    4. Resolve base runners

Flow per game:
    9+ innings, each with two half-innings of 3 outs.

Performance target: 10,000 games in <10 seconds (rule-based mode).
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.models.sports.mlb.batted_ball_model import (
    BATTED_BALL_OUTCOMES,
    MLBBattedBallModel,
)
from app.analytics.models.sports.mlb.pitch_model import (
    PITCH_OUTCOMES,
    MLBPitchOutcomeModel,
)
from app.analytics.models.sports.mlb.run_expectancy_model import (
    MLBRunExpectancyModel,
    encode_base_state,
)

# Import base runner helpers from the existing game simulator.
from app.analytics.sports.mlb.game_simulator import (
    _advance_double,
    _advance_home_run,
    _advance_single,
    _advance_triple,
    _advance_walk,
)

_MAX_PITCHES_PER_PA = 20  # safety limit
_MAX_EXTRA_INNINGS = 10


class PitchSimulator:
    """Simulate MLB plate appearances at the pitch level."""

    def __init__(
        self,
        pitch_model: MLBPitchOutcomeModel | None = None,
        batted_ball_model: MLBBattedBallModel | None = None,
        run_expectancy_model: MLBRunExpectancyModel | None = None,
    ) -> None:
        self._pitch = pitch_model or MLBPitchOutcomeModel()
        self._batted_ball = batted_ball_model or MLBBattedBallModel()
        self._re = run_expectancy_model or MLBRunExpectancyModel()

    def simulate_plate_appearance(
        self,
        features: dict[str, Any] | None = None,
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one plate appearance pitch-by-pitch.

        Returns:
            Dict with ``result`` (walk/strikeout/single/etc.),
            ``pitches`` count, ``final_count``, and optionally
            ``batted_ball_result``.
        """
        if rng is None:
            rng = random.Random()
        features = features or {}

        balls = 0
        strikes = 0
        pitches = 0

        for _ in range(_MAX_PITCHES_PER_PA):
            pitch_features = {
                **features,
                "count_balls": balls,
                "count_strikes": strikes,
            }
            pitch_probs = self._pitch.predict_proba(pitch_features)
            pitch_result = _sample(pitch_probs, PITCH_OUTCOMES, rng)
            pitches += 1

            if pitch_result == "ball":
                balls += 1
                if balls >= 4:
                    return {
                        "result": "walk",
                        "pitches": pitches,
                        "final_count": f"{balls}-{strikes}",
                    }

            elif pitch_result in ("called_strike", "swinging_strike"):
                strikes += 1
                if strikes >= 3:
                    return {
                        "result": "strikeout",
                        "pitches": pitches,
                        "final_count": f"{balls}-{strikes}",
                    }

            elif pitch_result == "foul":
                if strikes < 2:
                    strikes += 1

            elif pitch_result == "in_play":
                bb_probs = self._batted_ball.predict_proba(features)
                bb_result = _sample(bb_probs, BATTED_BALL_OUTCOMES, rng)
                return {
                    "result": bb_result,
                    "pitches": pitches,
                    "final_count": f"{balls}-{strikes}",
                    "batted_ball_result": bb_result,
                }

        # Safety: max pitches reached
        return {
            "result": "out",
            "pitches": pitches,
            "final_count": f"{balls}-{strikes}",
        }


class PitchLevelGameSimulator:
    """Simulate a full MLB game at the pitch level.

    Drop-in replacement for MLBGameSimulator with ``simulate_game()``.
    """

    def __init__(
        self,
        pitch_model: MLBPitchOutcomeModel | None = None,
        batted_ball_model: MLBBattedBallModel | None = None,
        run_expectancy_model: MLBRunExpectancyModel | None = None,
    ) -> None:
        self._pa_sim = PitchSimulator(
            pitch_model, batted_ball_model, run_expectancy_model,
        )
        self._re = run_expectancy_model or MLBRunExpectancyModel()

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete game pitch-by-pitch.

        Args:
            game_context: May contain ``home_features`` and
                ``away_features`` dicts for batter/pitcher profiles.
            rng: Optional RNG for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            ``total_pitches``, and ``run_expectancy`` samples.
        """
        if rng is None:
            rng = random.Random()

        home_features = game_context.get("home_features", {})
        away_features = game_context.get("away_features", {})

        home_score = 0
        away_score = 0
        total_pitches = 0

        for inning in range(1, 10):
            runs, pitches = self._simulate_half_inning(away_features, rng)
            away_score += runs
            total_pitches += pitches

            if inning == 9 and home_score > away_score:
                break

            runs, pitches = self._simulate_half_inning(home_features, rng)
            home_score += runs
            total_pitches += pitches

            if inning == 9 and home_score > away_score:
                break

        extra = 0
        while home_score == away_score and extra < _MAX_EXTRA_INNINGS:
            runs, pitches = self._simulate_half_inning(away_features, rng)
            away_score += runs
            total_pitches += pitches
            runs, pitches = self._simulate_half_inning(home_features, rng)
            home_score += runs
            total_pitches += pitches
            extra += 1

        winner = "home" if home_score >= away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "total_pitches": total_pitches,
        }

    def _simulate_half_inning(
        self,
        features: dict[str, Any],
        rng: random.Random,
    ) -> tuple[int, int]:
        """Simulate one half-inning. Returns (runs, pitches)."""
        outs = 0
        bases = [False, False, False]
        runs = 0
        pitches = 0

        while outs < 3:
            pa = self._pa_sim.simulate_plate_appearance(features, rng)
            pitches += pa.get("pitches", 1)
            result = pa["result"]

            if result in ("strikeout", "out"):
                outs += 1
            elif result == "walk":
                runs += _advance_walk(bases)
            elif result == "single":
                runs += _advance_single(bases)
            elif result == "double":
                runs += _advance_double(bases)
            elif result == "triple":
                runs += _advance_triple(bases)
            elif result == "home_run":
                runs += _advance_home_run(bases)

        return runs, pitches


def _sample(
    probs: dict[str, float],
    outcomes: list[str],
    rng: random.Random,
) -> str:
    """Sample an outcome from a probability dict."""
    weights = [max(probs.get(o, 0.0), 0.0) for o in outcomes]
    total = sum(weights)
    if total <= 0:
        return rng.choice(outcomes)
    return rng.choices(outcomes, weights=weights, k=1)[0]
