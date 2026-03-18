"""MLB Monte Carlo game simulation.

Simulates individual MLB games at the plate-appearance level using
matchup probability distributions. Designed for high-volume use —
all calculations are stateless with no database calls.

Game flow:
    9 innings (or more for ties), each with two half-innings.
    Each half-inning runs plate appearances until 3 outs.
    Events are sampled from probability distributions produced
    by the matchup engine.
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.sports.mlb.constants import (
    DEFAULT_EVENT_PROBS_SUFFIXED as _DEFAULT_PROBS,
)
from app.analytics.sports.mlb.constants import (
    MAX_EXTRA_INNINGS as _MAX_EXTRA_INNINGS,
)
from app.analytics.sports.mlb.constants import (
    PA_EVENTS as EVENTS,
)


class MLBGameSimulator:
    """Simulate a single MLB game using plate-appearance probabilities."""

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete MLB game.

        Args:
            game_context: Must contain ``home_probabilities`` and
                ``away_probabilities`` dicts with event probability keys.
                Missing keys fall back to league-average defaults.
            rng: Optional ``random.Random`` instance for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            ``home_events``, ``away_events``, and ``innings_played``.
        """
        if rng is None:
            rng = random.Random()

        home_probs = _build_weights(game_context.get("home_probabilities", {}))
        away_probs = _build_weights(game_context.get("away_probabilities", {}))

        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        innings_played = 0

        # Regulation: 9 innings
        for inning in range(1, 10):
            innings_played = inning
            away_score += self._simulate_half_inning(away_probs, rng, away_events)
            # Bottom of 9th: skip if home already ahead
            if inning == 9 and home_score > away_score:
                break
            home_score += self._simulate_half_inning(home_probs, rng, home_events)
            # Walk-off in bottom of 9th
            if inning == 9 and home_score > away_score:
                break

        # Extra innings
        extra = 0
        while home_score == away_score and extra < _MAX_EXTRA_INNINGS:
            away_score += self._simulate_half_inning(away_probs, rng, away_events)
            home_score += self._simulate_half_inning(home_probs, rng, home_events)
            extra += 1
            innings_played += 1

        winner = "home" if home_score >= away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "home_events": home_events,
            "away_events": away_events,
            "innings_played": innings_played,
        }

    def _simulate_half_inning(
        self,
        weights: list[float],
        rng: random.Random,
        events: dict[str, int] | None = None,
    ) -> int:
        """Simulate one half-inning, returning runs scored."""
        outs = 0
        bases = [False, False, False]  # 1st, 2nd, 3rd
        runs = 0

        while outs < 3:
            event = rng.choices(EVENTS, weights=weights, k=1)[0]

            if events is not None:
                events[event] = events.get(event, 0) + 1
                events["pa_total"] = events.get("pa_total", 0) + 1

            if event in ("strikeout", "ball_in_play_out"):
                outs += 1

            elif event == "walk_or_hbp":
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

    # ------------------------------------------------------------------
    # Lineup-aware simulation
    # ------------------------------------------------------------------

    def simulate_game_with_lineups(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete MLB game with per-batter lineup weights.

        Args:
            game_context: Dict containing per-batter weight arrays.
                Expected keys:
                    ``home_lineup_weights`` / ``away_lineup_weights`` —
                        list of 9 weight arrays (vs starter).
                    ``home_bullpen_weights`` / ``away_bullpen_weights`` —
                        list of 9 weight arrays (vs bullpen).
                    ``starter_innings`` — float, inning after which the
                        bullpen takes over (default 6.0).
                Falls back to ``home_probabilities`` / ``away_probabilities``
                if lineup-level weights are not provided.
            rng: Optional ``random.Random`` instance for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            and ``innings_played``.
        """
        if rng is None:
            rng = random.Random()

        # -- resolve starter weights ------------------------------------
        if "home_lineup_weights" in game_context:
            home_starter_weights = game_context["home_lineup_weights"]
        else:
            w = _build_weights(game_context.get("home_probabilities", {}))
            home_starter_weights = [w] * 9

        if "away_lineup_weights" in game_context:
            away_starter_weights = game_context["away_lineup_weights"]
        else:
            w = _build_weights(game_context.get("away_probabilities", {}))
            away_starter_weights = [w] * 9

        # -- resolve bullpen weights ------------------------------------
        if "home_bullpen_weights" in game_context:
            home_bullpen_weights = game_context["home_bullpen_weights"]
        else:
            home_bullpen_weights = home_starter_weights

        if "away_bullpen_weights" in game_context:
            away_bullpen_weights = game_context["away_bullpen_weights"]
        else:
            away_bullpen_weights = away_starter_weights

        transition_inning = int(game_context.get("starter_innings", 6.0))

        home_score = 0
        away_score = 0
        home_lineup_idx = 0
        away_lineup_idx = 0
        innings_played = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()

        # Regulation: 9 innings
        for inning in range(1, 10):
            innings_played = inning

            # Determine weights based on starter / bullpen transition
            if inning <= transition_inning:
                away_weights = away_starter_weights
                home_weights = home_starter_weights
            else:
                away_weights = away_bullpen_weights
                home_weights = home_bullpen_weights

            # Top half — away bats
            runs, away_lineup_idx = self._simulate_half_inning_lineup(
                away_weights, away_lineup_idx, rng, away_events,
            )
            away_score += runs

            # Bottom of 9th: skip if home already ahead
            if inning == 9 and home_score > away_score:
                break

            # Bottom half — home bats
            runs, home_lineup_idx = self._simulate_half_inning_lineup(
                home_weights, home_lineup_idx, rng, home_events,
            )
            home_score += runs

            # Walk-off in bottom of 9th
            if inning == 9 and home_score > away_score:
                break

        # Extra innings (always use bullpen weights)
        extra = 0
        while home_score == away_score and extra < _MAX_EXTRA_INNINGS:
            runs, away_lineup_idx = self._simulate_half_inning_lineup(
                away_bullpen_weights, away_lineup_idx, rng, away_events,
            )
            away_score += runs

            runs, home_lineup_idx = self._simulate_half_inning_lineup(
                home_bullpen_weights, home_lineup_idx, rng, home_events,
            )
            home_score += runs

            extra += 1
            innings_played += 1

        winner = "home" if home_score >= away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "innings_played": innings_played,
            "home_events": home_events,
            "away_events": away_events,
        }

    def _simulate_half_inning_lineup(
        self,
        weights_list: list[list[float]],
        lineup_idx: int,
        rng: random.Random,
        events: dict[str, int] | None = None,
    ) -> tuple[int, int]:
        """Simulate one half-inning with per-batter weights.

        Args:
            weights_list: List of 9 pre-computed weight arrays, one per
                lineup slot.
            lineup_idx: Current position in the batting order (0-8).
            rng: Random instance.
            events: Optional event counter dict to accumulate into.

        Returns:
            Tuple of ``(runs_scored, new_lineup_idx)``.
        """
        outs = 0
        bases = [False, False, False]  # 1st, 2nd, 3rd
        runs = 0

        while outs < 3:
            weights = weights_list[lineup_idx % 9]
            event = rng.choices(EVENTS, weights=weights, k=1)[0]

            if events is not None:
                events[event] = events.get(event, 0) + 1
                events["pa_total"] = events.get("pa_total", 0) + 1

            if event in ("strikeout", "ball_in_play_out"):
                outs += 1

            elif event == "walk_or_hbp":
                runs += _advance_walk(bases)

            elif event == "single":
                runs += _advance_single(bases)

            elif event == "double":
                runs += _advance_double(bases)

            elif event == "triple":
                runs += _advance_triple(bases)

            elif event == "home_run":
                runs += _advance_home_run(bases)

            lineup_idx = (lineup_idx + 1) % 9

        return runs, lineup_idx


# ---------------------------------------------------------------------------
# Event counter helper
# ---------------------------------------------------------------------------


def _new_event_counts() -> dict[str, int]:
    """Return a fresh event counter dict with all PA event keys zeroed."""
    return {e: 0 for e in EVENTS} | {"pa_total": 0}


# ---------------------------------------------------------------------------
# Base-runner advancement helpers (simplified model)
# ---------------------------------------------------------------------------


def _advance_walk(bases: list[bool]) -> int:
    """Walk: batter to 1st, force advancement only."""
    runs = 0
    if bases[0]:
        if bases[1]:
            if bases[2]:
                runs += 1  # runner scores from 3rd
            bases[2] = True
        bases[1] = True
    bases[0] = True
    return runs


def _advance_single(bases: list[bool]) -> int:
    """Single: runners advance 1 base, runner on 2nd scores."""
    runs = 0
    if bases[2]:
        runs += 1
        bases[2] = False
    if bases[1]:
        runs += 1  # runner on 2nd scores on single
        bases[1] = False
    if bases[0]:
        bases[1] = True
        bases[0] = False
    bases[0] = True
    return runs


def _advance_double(bases: list[bool]) -> int:
    """Double: runners advance 2 bases."""
    runs = 0
    if bases[2]:
        runs += 1
        bases[2] = False
    if bases[1]:
        runs += 1
        bases[1] = False
    if bases[0]:
        bases[2] = True
        bases[0] = False
    bases[1] = True
    return runs


def _advance_triple(bases: list[bool]) -> int:
    """Triple: all runners score."""
    runs = sum(bases)
    bases[0] = False
    bases[1] = False
    bases[2] = True
    return runs


def _advance_home_run(bases: list[bool]) -> int:
    """Home run: all runners + batter score."""
    runs = sum(bases) + 1
    bases[0] = False
    bases[1] = False
    bases[2] = False
    return runs


# ---------------------------------------------------------------------------
# Weight construction
# ---------------------------------------------------------------------------


def _build_weights(probs: dict[str, float]) -> list[float]:
    """Convert a probability dict into ordered weights for ``EVENTS``.

    Maps ``*_probability`` keys to event order.  ``ball_in_play_out``
    absorbs the remaining probability mass after all named events.
    """
    k = max(probs.get("strikeout_probability", _DEFAULT_PROBS["strikeout_probability"]), 0.0)
    bb = max(probs.get("walk_or_hbp_probability", _DEFAULT_PROBS["walk_or_hbp_probability"]), 0.0)
    single = max(probs.get("single_probability", _DEFAULT_PROBS["single_probability"]), 0.0)
    double = max(probs.get("double_probability", _DEFAULT_PROBS["double_probability"]), 0.0)
    triple = max(probs.get("triple_probability", _DEFAULT_PROBS["triple_probability"]), 0.0)
    hr = max(probs.get("home_run_probability", _DEFAULT_PROBS["home_run_probability"]), 0.0)

    named_total = k + bb + single + double + triple + hr
    out_prob = max(1.0 - named_total, 0.0)

    # Order matches EVENTS: strikeout, ball_in_play_out, walk_or_hbp, single, double, triple, home_run
    return [k, out_prob, bb, single, double, triple, hr]
