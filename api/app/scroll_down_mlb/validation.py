"""Internal-consistency validation for built play cards.

Port of `scroll-down-web/web/src/lib/play-validation.ts`, plus Phase 3
additions:

  * duplicate selected play IDs
  * pre-reveal final-score leakage detector at the DTO boundary

Severity policy is enforced by `service.apply_validation_policy`:

  * `live` decks  — all findings ship as warnings, never block
  * `official`    — `severity=error` blocks the deck
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .internal_types import BuiltPlayCard
from .schemas import ValidationSeverity, ValidationWarning

# Validation codes. Severity defaults to `error` for any contradiction in
# the data; the live policy downgrades them at the service layer.
_ERROR_MESSAGES: dict[str, str] = {
    "score_delta_without_runner_scored": "Score changed but no runner crossed home.",
    "runner_scored_without_score_delta": "Runner reached home but score did not change.",
    "home_run_without_score_delta": "Home run did not increment the score.",
    "strikeout_without_out_increment": "Strikeout without an out increment.",
    "extra_base_hit_wrong_batter_destination": "Batter ended on the wrong base for the event.",
    "double_play_without_runner_to_force": "Double play with no runner available to force.",
    "triple_play_without_two_runners": "Triple play needs two prior runners on base.",
    "runner_label_not_on_rendered_base": "Runner label does not match a rendered base.",
    "movement_path_missing_for_runner_change": "Runner state changed without a movement path.",
    "duplicate_selected_play_id": "A play was selected for the deck more than once.",
    "final_score_leak_in_pre_reveal": (
        "Pre-reveal payload contains a final-score-shaped field."
    ),
    "missing_mlb_pitchers": "Upstream did not provide mlbPitchers; pitcher of record degraded.",
}


_EXPECTED_BATTER_DEST: dict[str, str] = {
    "single": "first",
    "double": "second",
    "triple": "third",
    "home_run": "home",
    "walk": "first",
    "hit_by_pitch": "first",
    "catcher_interference": "first",
    "error": "first",
    "fielders_choice": "first",
}


def _make(code: str, severity: ValidationSeverity, play_id: str | None = None) -> ValidationWarning:
    return ValidationWarning(
        code=code,
        severity=severity,
        message=_ERROR_MESSAGES.get(code, code),
        play_id=play_id,
    )


def _occupied(state: dict[str, bool]) -> int:
    return (
        (1 if state.get("first") else 0)
        + (1 if state.get("second") else 0)
        + (1 if state.get("third") else 0)
    )


# Severity assignments: codes in `_HARD_ERRORS` are unrecoverable
# contradictions in the game state (a home run that didn't score, a double
# play with nobody on base) and block official generation. Everything else
# is a diagnostic — the TS code logs these to console but always ships the
# card. Matching that behavior here means they ship as WARNING and don't
# block official decks.
_HARD_ERRORS = frozenset(
    {
        "home_run_without_score_delta",
        "double_play_without_runner_to_force",
        "triple_play_without_two_runners",
        "duplicate_selected_play_id",
        "final_score_leak_in_pre_reveal",
    }
)


def _severity_for(code: str) -> ValidationSeverity:
    return (
        ValidationSeverity.error
        if code in _HARD_ERRORS
        else ValidationSeverity.warning
    )


def _emit(code: str, play_id: str | None = None) -> ValidationWarning:
    return _make(code, _severity_for(code), play_id)


def validate_play_card(card: BuiltPlayCard) -> list[ValidationWarning]:
    """Return findings for a single play card. Mirrors the TS validator.

    Severity follows `_HARD_ERRORS`: only true game-state contradictions
    (HR with no run, DP with no runner) escalate to error and block
    official generation. Diagnostics ship as warnings — matching the TS
    behavior of logging-and-shipping.
    """
    findings: list[ValidationWarning] = []
    pid = str(card.play_index)

    advances = card.advances or []
    visual_scores = sum(1 for a in advances if a.to == "home")
    reported_runs = (
        (card.score_after_home - card.score_before_home)
        + (card.score_after_away - card.score_before_away)
    )
    outs_delta = card.outs_after - card.outs_before

    if reported_runs > 0 and visual_scores == 0:
        findings.append(_emit("score_delta_without_runner_scored", pid))
    if reported_runs == 0 and visual_scores > 0:
        findings.append(_emit("runner_scored_without_score_delta", pid))

    if card.event_type == "home_run" and reported_runs == 0:
        findings.append(_emit("home_run_without_score_delta", pid))
    if card.event_type == "strikeout" and outs_delta < 1:
        batter_reached = any(a.from_base == "home" and a.to != "out" for a in advances)
        if not batter_reached:
            findings.append(_emit("strikeout_without_out_increment", pid))

    expected = _EXPECTED_BATTER_DEST.get(card.event_type or "")
    if expected:
        batter_adv = next((a for a in advances if a.from_base == "home"), None)
        if batter_adv and batter_adv.to != expected:
            findings.append(_emit("extra_base_hit_wrong_batter_destination", pid))

    if card.event_type == "double_play" and _occupied(card.base_state_before) < 1:
        findings.append(_emit("double_play_without_runner_to_force", pid))
    if card.event_type == "triple_play" and _occupied(card.base_state_before) < 2:
        findings.append(_emit("triple_play_without_two_runners", pid))

    return findings


def validate_no_duplicate_play_ids(
    play_indices: Iterable[int],
) -> list[ValidationWarning]:
    """Catch the same play getting selected twice — would render incoherent."""
    seen: set[int] = set()
    dups: set[int] = set()
    for pid in play_indices:
        if pid in seen:
            dups.add(pid)
        else:
            seen.add(pid)
    return [_emit("duplicate_selected_play_id", str(pid)) for pid in sorted(dups)]


# Field names that must not appear anywhere in a pre-reveal deck DTO.
_FORBIDDEN_PRE_REVEAL_KEYS = frozenset(
    {
        "homeScore",
        "awayScore",
        "score",
        "scoreAfter",
        "finalScore",
        "winner",
        "winnerTeamId",
        "winningTeam",
    }
)


def _walk_keys(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_keys(v)


def validate_no_final_score_leak(payload: dict[str, Any]) -> list[ValidationWarning]:
    """Last-mile sanity check: scan the serialized DTO for forbidden keys.

    Belt-and-suspenders against a future PR adding a "convenience" final-score
    field to the deck schema.
    """
    keys = set(_walk_keys(payload))
    leaked = keys & _FORBIDDEN_PRE_REVEAL_KEYS
    if not leaked:
        return []
    return [
        ValidationWarning(
            code="final_score_leak_in_pre_reveal",
            severity=ValidationSeverity.error,
            message=(
                f"{_ERROR_MESSAGES['final_score_leak_in_pre_reveal']} "
                f"Leaked keys: {sorted(leaked)}"
            ),
            play_id=None,
        )
    ]


def warning_catalog() -> dict[str, str]:
    return dict(_ERROR_MESSAGES)


__all__ = [
    "validate_play_card",
    "validate_no_duplicate_play_ids",
    "validate_no_final_score_leak",
    "warning_catalog",
]
