"""Rhythm planner — pacing decisions for the catch-up deck.

Port of `scroll-down-web/web/src/lib/rhythm-planner.ts`.

Inserts pacing cards between play cards:

  * inning-transition  — between displayed plays in different halves, only
                         when the previous half was MEANINGFUL
  * quiet-stretch      — when 3+ half-innings pass with no displayed plays
  * late-game          — first time we cross into the 7th in a game
                         within 4 runs
  * final-setup        — before the last play card when 9th+ and ≤2-run margin

Meaningfulness rule for inning-transition:
  - 2+ runs scored, OR
  - lead change occurred, OR
  - tying run scored, OR
  - inning 7+ AND scored at least 1 run

Quiet-stretch budget capped at 2 per deck so sparse decks don't dribble out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .deck_builder import ordinal
from .internal_types import BuiltPlayCard, HalfInningMeta

# Output type: a deck is an ordered list of either built play cards or
# rhythm/scene dicts. Rhythm/scene cards stay as dicts because they have a
# unique shape (label/subtitle/score) different from BuiltPlayCard.
DeckItem = BuiltPlayCard | dict[str, Any]


@dataclass
class PlannerReportEntry:
    card_id: str
    kind: str
    reason: str
    after_play_index: int | None = None
    before_play_index: int | None = None


@dataclass
class PlannerReport:
    rhythm: list[PlannerReportEntry] = field(default_factory=list)


QUIET_STRETCH_BUDGET = 2


def _half_index(inning: int, half: str) -> int:
    return inning * 2 + (1 if half == "bottom" else 0)


def _describe_score_state(home: int, away: int, home_abbr: str, away_abbr: str) -> str:
    diff = home - away
    if diff == 0:
        if home == 0:
            return "Still scoreless."
        return f"Tied at {home}."
    leader = home_abbr if diff > 0 else away_abbr
    margin = abs(diff)
    if margin == 1:
        return f"{leader} lead by 1."
    return f"{leader} lead by {margin}."


def _quiet_flavor(home: int, away: int) -> str:
    diff = abs(home - away)
    if diff == 0:
        return "Both pitchers in command."
    if diff <= 2:
        return "The score holds."
    return "Neither side scratches."


# ---------------------------------------------------------------------------
# Card builders
# ---------------------------------------------------------------------------


def _build_inning_transition(
    prev: BuiltPlayCard, curr: BuiltPlayCard, home_abbr: str, away_abbr: str
) -> dict[str, Any]:
    phase = (
        "end"
        if prev.inning_half == "bottom" or prev.inning < curr.inning
        else "mid"
    )
    head = prev.inning
    label = (
        f"END {ordinal(head).upper()}"
        if phase == "end"
        else f"MID {ordinal(head).upper()}"
    )
    return {
        "kind": "inning-transition",
        "gameId": prev.game_id,
        "cardId": (
            f"{prev.game_id}-tx-{prev.inning}-{prev.inning_half}-"
            f"{curr.inning}-{curr.inning_half}"
        ),
        "label": label,
        "phase": phase,
        "score": {"home": prev.score_after_home, "away": prev.score_after_away},
        "homeTeamAbbr": home_abbr,
        "awayTeamAbbr": away_abbr,
        "subtitle": _describe_score_state(
            prev.score_after_home, prev.score_after_away, home_abbr, away_abbr
        ),
        "fromInning": prev.inning,
        "fromHalf": prev.inning_half,
        "toInning": curr.inning,
        "toHalf": curr.inning_half,
    }


def _build_quiet_stretch(
    prev: BuiltPlayCard, curr: BuiltPlayCard, home_abbr: str, away_abbr: str
) -> dict[str, Any]:
    passed_top = (
        curr.inning if curr.inning_half == "bottom" else max(prev.inning, curr.inning - 1)
    )
    label = f"THROUGH {ordinal(passed_top).upper()}"
    score_text = _describe_score_state(
        prev.score_after_home, prev.score_after_away, home_abbr, away_abbr
    )
    flavor = _quiet_flavor(prev.score_after_home, prev.score_after_away)
    return {
        "kind": "quiet-stretch",
        "gameId": prev.game_id,
        "cardId": (
            f"{prev.game_id}-qs-{prev.inning}-{prev.inning_half}-"
            f"{curr.inning}-{curr.inning_half}"
        ),
        "label": label,
        "subtitle": f"{score_text} {flavor}".strip(),
        "score": {"home": prev.score_after_home, "away": prev.score_after_away},
        "homeTeamAbbr": home_abbr,
        "awayTeamAbbr": away_abbr,
        "fromInning": prev.inning,
        "fromHalf": prev.inning_half,
        "toInning": curr.inning,
        "toHalf": curr.inning_half,
    }


def _build_late_game(curr: BuiltPlayCard, home_abbr: str, away_abbr: str) -> dict[str, Any]:
    margin = abs(curr.score_before_home - curr.score_before_away)
    if margin == 0:
        subtitle = f"Tied entering the {ordinal(curr.inning)}."
    else:
        subtitle = (
            _describe_score_state(
                curr.score_before_home, curr.score_before_away, home_abbr, away_abbr
            )
            + " Every runner matters now."
        )
    return {
        "kind": "late-game",
        "gameId": curr.game_id,
        "cardId": f"{curr.game_id}-lg-{curr.inning}-{curr.inning_half}",
        "label": "LATE INNINGS",
        "subtitle": subtitle,
        "score": {"home": curr.score_before_home, "away": curr.score_before_away},
        "homeTeamAbbr": home_abbr,
        "awayTeamAbbr": away_abbr,
        "toInning": curr.inning,
        "toHalf": curr.inning_half,
    }


def _build_final_setup(
    curr: BuiltPlayCard, home_abbr: str, away_abbr: str
) -> dict[str, Any]:
    margin = abs(curr.score_before_home - curr.score_before_away)
    half = "Top" if curr.inning_half == "top" else "Bottom"
    batting_team_leads = (
        (curr.inning_half == "bottom" and curr.score_before_home > curr.score_before_away)
        or (curr.inning_half == "top" and curr.score_before_away > curr.score_before_home)
    )
    if margin == 0:
        subtitle = f"{half} {ordinal(curr.inning)}, tied."
    elif batting_team_leads:
        subtitle = f"{half} {ordinal(curr.inning)}. Hold the lead."
    else:
        subtitle = f"{half} {ordinal(curr.inning)}. Down to the wire."
    return {
        "kind": "final-setup",
        "gameId": curr.game_id,
        "cardId": f"{curr.game_id}-fs-{curr.inning}-{curr.inning_half}",
        "label": "FINAL APPROACH",
        "subtitle": subtitle,
        "score": {"home": curr.score_before_home, "away": curr.score_before_away},
        "homeTeamAbbr": home_abbr,
        "awayTeamAbbr": away_abbr,
        "toInning": curr.inning,
        "toHalf": curr.inning_half,
    }


# ---------------------------------------------------------------------------
# Rule selection
# ---------------------------------------------------------------------------


def _half_meaningfulness(
    prev_inning: int, meta: HalfInningMeta | None
) -> tuple[bool, str]:
    if not meta:
        return False, "no activity"
    if meta.scored_runs >= 2:
        return True, f"{meta.scored_runs} runs scored"
    if meta.had_lead_change:
        return True, "lead change"
    if meta.had_tying:
        return True, "tying run"
    if prev_inning >= 7 and meta.scored_runs >= 1:
        return True, "late-inning scoring"
    if meta.scored_runs == 1:
        return False, "single run, no leverage — suppressed"
    return False, "silent half — suppressed"


def _decide_between(
    prev: BuiltPlayCard | None,
    curr: BuiltPlayCard,
    half_meta: dict[str, HalfInningMeta],
    home_abbr: str,
    away_abbr: str,
    late_game_emitted: bool,
) -> list[tuple[dict[str, Any], str]]:
    if not prev:
        return []
    prev_hi = _half_index(prev.inning, prev.inning_half)
    curr_hi = _half_index(curr.inning, curr.inning_half)
    spanned = curr_hi - prev_hi
    if spanned <= 0:
        return []
    out: list[tuple[dict[str, Any], str]] = []
    if spanned >= 3:
        out.append(
            (
                _build_quiet_stretch(prev, curr, home_abbr, away_abbr),
                f"compressed {spanned} silent half-innings",
            )
        )
    else:
        meta = half_meta.get(f"{prev.inning}:{prev.inning_half}")
        meaningful, reason = _half_meaningfulness(prev.inning, meta)
        if meaningful:
            out.append(
                (_build_inning_transition(prev, curr, home_abbr, away_abbr), reason)
            )
    margin = abs(curr.score_before_home - curr.score_before_away)
    entering_late = (
        not late_game_emitted
        and prev.inning < 7
        and curr.inning >= 7
        and margin <= 4
    )
    if entering_late:
        out.append(
            (
                _build_late_game(curr, home_abbr, away_abbr),
                f"crossed into inning 7+ with margin {margin}",
            )
        )
    return out


def _maybe_final_setup(
    curr: BuiltPlayCard, home_abbr: str, away_abbr: str
) -> tuple[dict[str, Any], str] | None:
    if curr.inning < 9:
        return None
    margin = abs(curr.score_before_home - curr.score_before_away)
    if margin > 2:
        return None
    return (
        _build_final_setup(curr, home_abbr, away_abbr),
        f"9th-inning final play with margin {margin}",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_deck_with_report(
    *,
    scene: dict[str, Any] | None,
    play_cards: list[BuiltPlayCard],
    half_inning_meta: dict[str, HalfInningMeta],
    home_team_abbr: str,
    away_team_abbr: str,
) -> tuple[list[DeckItem], PlannerReport]:
    """Plan the deck. Returns ordered cards + a report explaining each
    rhythm decision."""
    out: list[DeckItem] = []
    report = PlannerReport()
    next_index = 0

    if scene:
        scene_card = dict(scene)
        scene_card["index"] = next_index
        out.append(scene_card)
        next_index += 1

    prev: BuiltPlayCard | None = None
    late_game_emitted = False
    quiet_count = 0

    for i, curr in enumerate(play_cards):
        is_last = i == len(play_cards) - 1

        between = _decide_between(
            prev, curr, half_inning_meta, home_team_abbr, away_team_abbr, late_game_emitted
        )
        for card, reason in between:
            if card["kind"] == "quiet-stretch":
                if quiet_count >= QUIET_STRETCH_BUDGET:
                    continue
                quiet_count += 1
            card_with_index = dict(card)
            card_with_index["index"] = next_index
            out.append(card_with_index)
            report.rhythm.append(
                PlannerReportEntry(
                    card_id=card["cardId"],
                    kind=card["kind"],
                    reason=reason,
                    after_play_index=prev.play_index if prev else None,
                    before_play_index=curr.play_index,
                )
            )
            next_index += 1
            if card["kind"] == "late-game":
                late_game_emitted = True

        if is_last:
            setup = _maybe_final_setup(curr, home_team_abbr, away_team_abbr)
            if setup:
                card, reason = setup
                card_with_index = dict(card)
                card_with_index["index"] = next_index
                out.append(card_with_index)
                report.rhythm.append(
                    PlannerReportEntry(
                        card_id=card["cardId"],
                        kind=card["kind"],
                        reason=reason,
                        before_play_index=curr.play_index,
                    )
                )
                next_index += 1

        # Append the play card itself.
        curr.sort_order = next_index
        out.append(curr)
        next_index += 1
        prev = curr

    return out, report


def plan_deck(
    *,
    scene: dict[str, Any] | None,
    play_cards: list[BuiltPlayCard],
    half_inning_meta: dict[str, HalfInningMeta],
    home_team_abbr: str,
    away_team_abbr: str,
) -> list[DeckItem]:
    deck, _ = plan_deck_with_report(
        scene=scene,
        play_cards=play_cards,
        half_inning_meta=half_inning_meta,
        home_team_abbr=home_team_abbr,
        away_team_abbr=away_team_abbr,
    )
    return deck


__all__ = [
    "DeckItem",
    "PlannerReport",
    "PlannerReportEntry",
    "plan_deck",
    "plan_deck_with_report",
]
