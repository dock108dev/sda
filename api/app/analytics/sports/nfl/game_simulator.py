"""NFL Monte Carlo game simulation.

Simulates individual NFL games at the drive level. Each drive
resolves as one of: touchdown, field goal, punt, turnover,
turnover on downs, or end of half.

Unlike possession-based sports (NBA, NCAAB), NFL starters play
nearly every snap, so the "rotation" dimension is QB/offense
quality vs opposing defense quality rather than starter/bench units.

Game flow:
    2 halves, each with ~6 drives per team.
    Drives alternate between teams (simplified kickoff model).
    Touchdowns → extra point attempt (or rare 2-point).
    Field goals → 3 points at ~85% success rate.
    Tied after regulation → overtime (modified sudden death).
"""

from __future__ import annotations

import random
from typing import Any

from app.analytics.sports.nfl.constants import (
    DEFAULT_DRIVE_PROBS_SUFFIXED as _DEFAULT_PROBS,
)
from app.analytics.sports.nfl.constants import (
    DRIVE_OUTCOMES as _DRIVE_OUTCOMES,
)
from app.analytics.sports.nfl.constants import (
    DRIVES_PER_HALF as _DRIVES_PER_HALF,
)
from app.analytics.sports.nfl.constants import (
    EXTRA_POINT_SUCCESS_RATE as _XP_RATE,
)
from app.analytics.sports.nfl.constants import (
    FIELD_GOAL_SUCCESS_RATE as _FG_RATE,
)
from app.analytics.sports.nfl.constants import (
    MAX_OVERTIMES as _MAX_OVERTIMES,
)
from app.analytics.sports.nfl.constants import (
    OT_DRIVES as _OT_DRIVES,
)
from app.analytics.sports.nfl.constants import (
    TWO_POINT_ATTEMPT_RATE as _TWO_PT_ATT_RATE,
)
from app.analytics.sports.nfl.constants import (
    TWO_POINT_SUCCESS_RATE as _TWO_PT_RATE,
)

# Outcomes used for weighted sampling (excludes end_of_half which is
# handled structurally at the end of each half).
_SAMPLE_OUTCOMES: list[str] = [
    "touchdown",
    "field_goal",
    "punt",
    "turnover",
    "turnover_on_downs",
]


class NFLGameSimulator:
    """Simulate a single NFL game using drive-based probabilities."""

    def simulate_game(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """Simulate one complete NFL game.

        Args:
            game_context: Must contain ``home_probabilities`` and
                ``away_probabilities`` dicts with drive outcome
                probability keys. Missing keys fall back to defaults.
            rng: Optional ``random.Random`` instance for determinism.

        Returns:
            Dict with ``home_score``, ``away_score``, ``winner``,
            ``home_events``, ``away_events``, ``periods_played``,
            and ``went_to_overtime``.
        """
        if rng is None:
            rng = random.Random()

        home_probs = game_context.get("home_probabilities", {})
        away_probs = game_context.get("away_probabilities", {})

        home_weights = _build_weights(home_probs)
        away_weights = _build_weights(away_probs)

        home_xp = float(home_probs.get("xp_pct", _XP_RATE))
        away_xp = float(away_probs.get("xp_pct", _XP_RATE))
        home_fg = float(home_probs.get("fg_pct", _FG_RATE))
        away_fg = float(away_probs.get("fg_pct", _FG_RATE))

        return self._run_game(
            home_weights, away_weights,
            home_xp, away_xp, home_fg, away_fg,
            rng,
        )

    def simulate_game_with_lineups(
        self,
        game_context: dict[str, Any],
        rng: random.Random | None = None,
    ) -> dict[str, Any]:
        """NFL lineup-aware simulation using per-team drive profiles.

        NFL doesn't have rotation in the basketball sense — starters
        play every snap. The differentiation comes from team-specific
        drive outcome probabilities derived from QB quality, offensive
        EPA, and opposing defensive metrics.

        Expected ``game_context`` keys:
            home_drive_weights / away_drive_weights: list[float]
            home_xp_pct / away_xp_pct: float
            home_fg_pct / away_fg_pct: float

        Falls back to ``simulate_game`` if drive weight keys absent.
        """
        if "home_drive_weights" not in game_context:
            return self.simulate_game(game_context, rng)

        if rng is None:
            rng = random.Random()

        home_weights = game_context["home_drive_weights"]
        away_weights = game_context["away_drive_weights"]
        home_xp = float(game_context.get("home_xp_pct", _XP_RATE))
        away_xp = float(game_context.get("away_xp_pct", _XP_RATE))
        home_fg = float(game_context.get("home_fg_pct", _FG_RATE))
        away_fg = float(game_context.get("away_fg_pct", _FG_RATE))

        return self._run_game(
            home_weights, away_weights,
            home_xp, away_xp, home_fg, away_fg,
            rng,
        )

    def _run_game(
        self,
        home_weights: list[float],
        away_weights: list[float],
        home_xp: float,
        away_xp: float,
        home_fg: float,
        away_fg: float,
        rng: random.Random,
    ) -> dict[str, Any]:
        """Core game simulation logic shared by both modes."""
        home_score = 0
        away_score = 0
        home_events = _new_event_counts()
        away_events = _new_event_counts()
        went_to_overtime = False

        # First half: away receives kickoff (home defers, common NFL strategy)
        # So away drives first, home drives second
        for _drive in range(_DRIVES_PER_HALF):
            away_score += _resolve_drive(
                away_weights, rng, away_events, away_xp, away_fg,
            )
            home_score += _resolve_drive(
                home_weights, rng, home_events, home_xp, home_fg,
            )

        # Second half: home receives kickoff
        for _drive in range(_DRIVES_PER_HALF):
            home_score += _resolve_drive(
                home_weights, rng, home_events, home_xp, home_fg,
            )
            away_score += _resolve_drive(
                away_weights, rng, away_events, away_xp, away_fg,
            )

        # Overtime (modified sudden death: both teams get at least 1 drive)
        if home_score == away_score:
            went_to_overtime = True
            for _ot in range(_MAX_OVERTIMES):
                # Coin toss — 50/50 who receives
                if rng.random() < 0.5:
                    first_w, first_ev, first_xp, first_fg = home_weights, home_events, home_xp, home_fg
                    second_w, second_ev, second_xp, second_fg = away_weights, away_events, away_xp, away_fg
                    first_side, second_side = "home", "away"
                else:
                    first_w, first_ev, first_xp, first_fg = away_weights, away_events, away_xp, away_fg
                    second_w, second_ev, second_xp, second_fg = home_weights, home_events, home_xp, home_fg
                    first_side, second_side = "away", "home"

                for drive_num in range(_OT_DRIVES):
                    # First team drives
                    pts1 = _resolve_drive(first_w, rng, first_ev, first_xp, first_fg)
                    if first_side == "home":
                        home_score += pts1
                    else:
                        away_score += pts1

                    # If first drive is a TD, game over (sudden death after both had 1 drive)
                    if drive_num == 0 and pts1 >= 6:
                        break

                    # Second team drives
                    pts2 = _resolve_drive(second_w, rng, second_ev, second_xp, second_fg)
                    if second_side == "home":
                        home_score += pts2
                    else:
                        away_score += pts2

                    # After both teams have had at least 1 drive, any score wins
                    if home_score != away_score:
                        break

                if home_score != away_score:
                    break

        # If still tied after OT (rare), home wins (simplification)
        winner = "home" if home_score >= away_score else "away"

        return {
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "home_events": home_events,
            "away_events": away_events,
            "periods_played": 5 if went_to_overtime else 4,
            "went_to_overtime": went_to_overtime,
        }


# ---------------------------------------------------------------------------
# Drive resolution
# ---------------------------------------------------------------------------


def _resolve_drive(
    weights: list[float],
    rng: random.Random,
    events: dict[str, int],
    xp_pct: float,
    fg_pct: float,
) -> int:
    """Resolve a single drive, returning points scored."""
    outcome = rng.choices(_SAMPLE_OUTCOMES, weights=weights, k=1)[0]
    events[outcome] = events.get(outcome, 0) + 1
    events["drives_total"] = events.get("drives_total", 0) + 1

    if outcome == "touchdown":
        # Extra point or 2-point conversion
        if rng.random() < _TWO_PT_ATT_RATE:
            bonus = 2 if rng.random() < _TWO_PT_RATE else 0
        else:
            bonus = 1 if rng.random() < xp_pct else 0
        return 6 + bonus

    if outcome == "field_goal":
        if rng.random() < fg_pct:
            return 3
        return 0  # Missed FG, no points

    # punt, turnover, turnover_on_downs → 0 points
    return 0


# ---------------------------------------------------------------------------
# Event counter helper
# ---------------------------------------------------------------------------


def _new_event_counts() -> dict[str, int]:
    """Return a fresh event counter dict."""
    counts: dict[str, int] = {o: 0 for o in _SAMPLE_OUTCOMES}
    counts["drives_total"] = 0
    return counts


# ---------------------------------------------------------------------------
# Weight construction
# ---------------------------------------------------------------------------


def _build_weights(probs: dict[str, float]) -> list[float]:
    """Convert a probability dict into ordered weights for drive outcomes.

    ``punt`` absorbs the remaining probability mass after all named
    events so weights always sum to ~1.0.

    Order matches ``_SAMPLE_OUTCOMES``:
    touchdown, field_goal, punt, turnover, turnover_on_downs
    """
    td = max(probs.get("touchdown_probability", _DEFAULT_PROBS["touchdown_probability"]), 0.0)
    fg = max(probs.get("field_goal_probability", _DEFAULT_PROBS["field_goal_probability"]), 0.0)
    tov = max(probs.get("turnover_probability", _DEFAULT_PROBS["turnover_probability"]), 0.0)
    downs = max(probs.get("turnover_on_downs_probability", _DEFAULT_PROBS["turnover_on_downs_probability"]), 0.0)

    named_total = td + fg + tov + downs
    punt = max(1.0 - named_total, 0.0)

    return [td, fg, punt, tov, downs]
