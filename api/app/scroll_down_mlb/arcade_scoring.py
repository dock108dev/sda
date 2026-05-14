"""Arcade pressure/difficulty scoring for daily MLB moment selection.

Pure functions deriving arcade-style intensity metrics from leverage
signals already produced by the deck-builder pipeline. The arcade
frontend uses these to rank, label, and visually pace each daily
pressure moment.

No DB access, no I/O — inputs are plain ``TimelineEntry``-derived
scalars plus the ``BuiltPlayCard.leverage_tier`` integer. The caller
sources those from the matching pipeline objects; this module only does
math.
"""

from __future__ import annotations

from typing import Literal

PressureTier = Literal["low", "medium", "high", "extreme"]

_LEVERAGE_BASE: dict[int, int] = {0: 30, 1: 55, 2: 75}
_DEFAULT_BASE = 30
_DIFFICULTY_MAX = 100
_MAX_OUTS_BEFORE_REC = 2


def difficulty_score(
    inning: int,
    half: str,
    outs_before: int,
    base_state_before: dict[str, bool],
    score_margin: int,
    leverage_tier: int | None,
    is_tying_play: bool,
    is_lead_change_play: bool,
    is_late_leverage: bool,
) -> int:
    """Compute arcade difficulty (0-100) from per-play leverage signals.

    Higher = more pressure. The score blends a leverage-tier base with
    additive bonuses for late-game / tying / lead-change context and
    situational weight from runners on, outs remaining, and inning depth.
    Result is clamped to ``[0, 100]``.
    """
    base = _LEVERAGE_BASE.get(leverage_tier, _DEFAULT_BASE) if leverage_tier is not None else _DEFAULT_BASE

    bonus = 0
    if is_late_leverage:
        bonus += 10
    if is_tying_play:
        bonus += 8
    if is_lead_change_play:
        bonus += 6

    runners_on = sum(1 for occupied in base_state_before.values() if occupied)
    outs_remaining = max(0, _MAX_OUTS_BEFORE_REC - outs_before)
    situational = runners_on * 3 + outs_remaining * 2
    if inning >= 9:
        situational += 5

    # half and score_margin are accepted in the signature so callers can
    # pass the full TimelineEntry-derived context without revision when
    # the weighting formula grows to use them. They do not yet affect
    # the score.
    _ = (half, score_margin)

    return min(_DIFFICULTY_MAX, max(0, base + bonus + situational))


def pressure_tier(difficulty: int) -> PressureTier:
    """Map a 0-100 difficulty score to a four-step pressure label.

    Thresholds: low < 40, medium < 65, high < 90, extreme >= 90.
    """
    if difficulty < 40:
        return "low"
    if difficulty < 65:
        return "medium"
    if difficulty < 90:
        return "high"
    return "extreme"


def approximate_wpa(
    difficulty: int,
    runs_scored: int,
    is_scoring_play: bool,
    is_tying_play: bool,
    is_lead_change_play: bool,
) -> tuple[float, float, float]:
    """Approximate ``(wpaBefore, wpaAfter, wpaDelta)`` from leverage flags.

    Arcade-grade approximation — not a true win-expectancy model. All
    three returned values lie in ``[0.0, 1.0]`` and ``delta >= 0``.
    Defensive escapes (no runs, no tie, no lead change) still produce a
    non-zero swing scaled by the difficulty so the recap reads as a
    leverage shift rather than a null event.
    """
    leverage_factor = max(0.0, min(1.0, difficulty / 100.0))
    wpa_before = 0.30 + leverage_factor * 0.35

    outcome_weight = 0.0
    if is_lead_change_play:
        outcome_weight += 0.30
    if is_tying_play:
        outcome_weight += 0.15
    if is_scoring_play:
        outcome_weight += 0.05
    outcome_weight += min(0.20, max(0, runs_scored) * 0.05)

    if outcome_weight == 0.0:
        outcome_weight = leverage_factor * 0.25

    wpa_before = max(0.0, min(1.0, wpa_before))
    wpa_after = max(0.0, min(1.0, wpa_before + outcome_weight))
    wpa_delta = max(0.0, wpa_after - wpa_before)
    return wpa_before, wpa_after, wpa_delta


__all__ = [
    "PressureTier",
    "approximate_wpa",
    "difficulty_score",
    "pressure_tier",
]
