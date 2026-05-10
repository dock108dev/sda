"""Result chip labels.

Port of `scroll-down-web/web/src/lib/result-chip.ts`.

Maps (eventType, description) -> {primary, secondary} chip labels:
  STRIKEOUT, GRAND SLAM, INFIELD SINGLE, etc.

`secondary` is validated against runner advances so we never claim
"RUN SCORES" when no runner can be visually accounted for at home.

Tier classification ("ChipTier" 0-3) drives visual weight on the chip;
late+close+leverage contexts can boost tiers 1-2 by one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .internal_types import BuiltPlayCard

# ---------------------------------------------------------------------------
# Description signal regexes (case-insensitive)
# ---------------------------------------------------------------------------

_CALLED_STRIKE = re.compile(r"\bcalled\s*out\s*on\s*strikes\b", re.IGNORECASE)
_SWINGING_STRIKE = re.compile(r"\bstrikes?\s*out\s*swinging\b", re.IGNORECASE)
_FOUL_TIP = re.compile(r"\bstrikes?\s*out\s*on\s*a\s*foul\s*tip\b", re.IGNORECASE)
_SAC_FLY = re.compile(r"\bsacrifice\s*fly\b|\bsac\s*fly\b", re.IGNORECASE)
_SAC_BUNT = re.compile(r"\bsacrifice\s*bunt\b|\bsac\s*bunt\b", re.IGNORECASE)
_GRAND_SLAM = re.compile(r"\bgrand\s*slam\b", re.IGNORECASE)
_INSIDE_PARK = re.compile(r"\binside[-\s]?the[-\s]?park\b", re.IGNORECASE)
_FORCE_OUT = re.compile(r"\bforces?\s*out\b|\bforce\s*out\b", re.IGNORECASE)
_TAG_OUT = re.compile(r"\btagged?\s*out\b|\btag\s*out\b", re.IGNORECASE)
_POP_OUT = re.compile(r"\bpops?\s*out\b|\bpop[-\s]?up\b", re.IGNORECASE)
_LINE_OUT = re.compile(r"\blines?\s*out\b|\bline[-\s]?out\b", re.IGNORECASE)
_FLY_OUT = re.compile(r"\bflies\s*out\b|\bfly\s*out\b|\bfly\s*ball\b", re.IGNORECASE)
_GROUND_OUT = re.compile(r"\bgrounds?\s*out\b|\bground\s*out\b", re.IGNORECASE)
_INFIELD_SINGLE = re.compile(r"\binfield\s*single\b", re.IGNORECASE)
_BUNT_SINGLE = re.compile(r"\bbunt\s*single\b", re.IGNORECASE)
_INTENTIONAL = re.compile(r"\bintentional\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResultChipLabel:
    primary: str
    secondary: str | None = None


def _primary_for(event: str | None, description: str) -> str:
    if event == "strikeout":
        if _CALLED_STRIKE.search(description):
            return "CALLED STRIKE THREE"
        if _FOUL_TIP.search(description):
            return "STRIKEOUT"
        if _SWINGING_STRIKE.search(description):
            return "SWINGING STRIKE THREE"
        return "STRIKEOUT"
    if event == "walk":
        if _INTENTIONAL.search(description):
            return "INTENTIONAL WALK"
        return "WALK"
    if event == "hit_by_pitch":
        return "HIT BY PITCH"
    if event == "catcher_interference":
        return "CATCHER'S INTERFERENCE"
    if event == "single":
        if _INFIELD_SINGLE.search(description):
            return "INFIELD SINGLE"
        if _BUNT_SINGLE.search(description):
            return "BUNT SINGLE"
        return "SINGLE"
    if event == "double":
        return "DOUBLE"
    if event == "triple":
        return "TRIPLE"
    if event == "home_run":
        if _GRAND_SLAM.search(description):
            return "GRAND SLAM"
        if _INSIDE_PARK.search(description):
            return "INSIDE-THE-PARK HOME RUN"
        return "HOME RUN"
    if event == "double_play":
        return "DOUBLE PLAY"
    if event == "triple_play":
        return "TRIPLE PLAY"
    if event == "fielders_choice":
        return "FIELDER'S CHOICE"
    if event == "error":
        return "REACHED ON ERROR"
    if event == "stolen_base":
        return "STOLEN BASE"
    if event == "caught_stealing":
        return "CAUGHT STEALING"
    if event == "pickoff":
        return "PICKED OFF"
    if event == "balk":
        return "BALK"
    if event == "wild_pitch":
        return "WILD PITCH"
    if event == "passed_ball":
        return "PASSED BALL"
    if event == "sacrifice":
        if _SAC_FLY.search(description):
            return "SAC FLY"
        if _SAC_BUNT.search(description):
            return "SAC BUNT"
        return "SACRIFICE"
    if event == "field_out":
        if _POP_OUT.search(description):
            return "POP OUT"
        if _LINE_OUT.search(description):
            return "LINEOUT"
        if _FLY_OUT.search(description):
            return "FLYOUT"
        if _GROUND_OUT.search(description):
            return "GROUNDOUT"
        if _FORCE_OUT.search(description):
            return "FORCE OUT"
        if _TAG_OUT.search(description):
            return "TAG OUT"
        return "OUT"
    return "PLAY"


def _secondary_for(card: BuiltPlayCard) -> str | None:
    """Optional second line — usually run / inning marker.

    Validated against the actual visual scoring (advance.to == "home") so
    we never claim "RUN SCORES" without a runner crossing the plate.
    """
    reported_runs = (
        (card.score_after_home - card.score_before_home)
        + (card.score_after_away - card.score_before_away)
    )
    inning_over = card.outs_after >= 3

    if inning_over and card.event_type in ("double_play", "triple_play"):
        return "INNING OVER"

    visual_scores = sum(1 for a in card.advances if a.to == "home")
    safe_runs = min(reported_runs, visual_scores)
    if safe_runs > 0 and card.event_type != "home_run":
        if safe_runs == 1:
            return "RUN SCORES"
        return f"+{safe_runs} RUNS"

    if inning_over and card.event_type in ("field_out", "strikeout", "sacrifice"):
        return "INNING OVER"

    return None


def result_chip_label(card: BuiltPlayCard) -> ResultChipLabel:
    """Compute the (primary, secondary) chip label for a play card."""
    return ResultChipLabel(
        primary=_primary_for(card.event_type, card.description or ""),
        secondary=_secondary_for(card),
    )


# ---------------------------------------------------------------------------
# Tier classification (visual weight, 0-3)
# ---------------------------------------------------------------------------

_TIER_ZERO_PRIMARIES = frozenset(
    {
        "GROUNDOUT",
        "FLYOUT",
        "POP OUT",
        "LINEOUT",
        "FORCE OUT",
        "TAG OUT",
        "OUT",
        "WALK",
        "STRIKEOUT",
        "FIELDER'S CHOICE",
        "BALK",
        "WILD PITCH",
        "PASSED BALL",
        "HIT BY PITCH",
        "PLAY",
    }
)


def _base_tier(primary: str, secondary: str | None) -> int:
    if primary in ("HOME RUN", "GRAND SLAM", "INSIDE-THE-PARK HOME RUN", "TRIPLE PLAY"):
        return 3
    if secondary in ("+2 RUNS", "+3 RUNS", "+4 RUNS"):
        return 3
    if primary in ("DOUBLE", "TRIPLE", "DOUBLE PLAY"):
        return 2
    if secondary in ("RUN SCORES", "INNING OVER"):
        return 2
    if primary in _TIER_ZERO_PRIMARIES:
        return 0
    return 1


def _leverage_boost(base: int, card: BuiltPlayCard) -> int:
    if base in (0, 3):
        return base
    score_diff = abs(card.score_before_home - card.score_before_away)
    score_delta = (
        (card.score_after_home - card.score_before_home)
        + (card.score_after_away - card.score_before_away)
    )
    is_late = card.inning >= 8
    is_close = score_diff <= 2
    is_two_out = card.outs_before == 2
    is_loaded = (
        card.base_state_before.get("first", False)
        and card.base_state_before.get("second", False)
        and card.base_state_before.get("third", False)
    )
    is_walkoff_setup = (
        card.inning_half == "bottom" and card.inning >= 9 and score_diff <= 1
    )
    boost = 1 if (
        is_walkoff_setup
        or (is_late and is_close and is_two_out)
        or (is_late and is_close and is_loaded)
        or score_delta >= 3
    ) else 0
    return min(3, base + boost)


def result_chip_tier(card: BuiltPlayCard) -> int:
    label = result_chip_label(card)
    return _leverage_boost(_base_tier(label.primary, label.secondary), card)


__all__ = ["ResultChipLabel", "result_chip_label", "result_chip_tier"]
