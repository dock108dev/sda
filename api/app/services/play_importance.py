"""Backend-owned play importance and stream contract enrichment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.routers.sports.schemas.common import (
    PlayEntry,
    PlayImportance,
    PlayModeEligibility,
    ScoreObject,
)


class DetailContractError(ValueError):
    """Raised when a game detail stream cannot satisfy the v2 client contract."""


_DISPLAY_LABELS: dict[str, str] = {
    "home_run": "Home run",
    "field_out": "Out",
    "ground_out": "Out",
    "fly_out": "Out",
    "line_out": "Out",
    "pop_out": "Out",
    "force_out": "Force out",
    "strikeout": "Strikeout",
    "strike_out": "Strikeout",
    "single": "Single",
    "double": "Double",
    "triple": "Triple",
    "walk": "Walk",
    "base_on_balls": "Walk",
    "intent_walk": "Intentional walk",
    "hit_by_pitch": "Hit by pitch",
    "stolen_base": "Stolen base",
    "caught_stealing": "Caught stealing",
    "field_error": "Error",
    "wild_pitch": "Wild pitch",
    "passed_ball": "Passed ball",
    "balk": "Balk",
    "double_play": "Double play",
    "triple_play": "Triple play",
    "pickoff": "Pickoff",
    "free_throw": "Free throw",
    "freethrow": "Free throw",
    "2pt": "2-pointer",
    "2pt_made": "2-pointer",
    "3pt": "3-pointer",
    "3pt_made": "3-pointer",
    "made_shot": "Made shot",
    "layup": "Layup",
    "dunk": "Dunk",
    "foul": "Foul",
    "personal_foul": "Foul",
    "shooting_foul": "Shooting foul",
    "offensive_foul": "Offensive foul",
    "technical_foul": "Technical foul",
    "flagrant_foul": "Flagrant foul",
    "turnover": "Turnover",
    "block": "Block",
    "steal": "Steal",
    "offensive_rebound": "Offensive rebound",
    "defensive_rebound": "Defensive rebound",
    "goal": "Goal",
    "penalty": "Penalty",
    "delayed_penalty": "Delayed penalty",
    "touchdown": "Touchdown",
    "field_goal": "Field goal",
    "missed_field_goal": "Missed field goal",
    "blocked_field_goal": "Blocked field goal",
    "interception": "Interception",
    "fumble": "Fumble",
    "sack": "Sack",
    "first_down": "First down",
}

_NBA_STANDARD_SCORING = {
    "made_shot",
    "layup",
    "dunk",
    "2pt",
    "2pt_made",
    "3pt",
    "3pt_made",
    "free_throw",
    "freethrow",
}

_POSSESSION_SWING_TYPES = {
    "turnover",
    "steal",
    "block",
    "offensive_rebound",
    "interception",
    "fumble",
    "turnover_on_downs",
    "fourth_down_conversion",
    "fourth_down_stop",
}

_MLB_THREAT_ENDING_TYPES = {
    "double_play",
    "triple_play",
    "caught_stealing",
    "pickoff",
}


@dataclass(frozen=True)
class _PlayContext:
    index: int
    league_code: str
    home_abbr: str | None
    away_abbr: str | None
    final_index: int
    run_enders: set[int]


def enrich_play_importance(
    plays: list[PlayEntry],
    *,
    league_code: str,
    home_abbr: str | None,
    away_abbr: str | None,
) -> None:
    """Mutate plays with v2 detail-stream metadata.

    This is the contract boundary for stream clients: every play leaves with
    display labels, period labels, score progression, importance, and mode
    eligibility set by SDA.
    """
    if not plays:
        return

    final_index = max((play.play_index for play in plays), default=plays[-1].play_index)
    run_enders = _detect_run_ending_plays(plays)
    code = league_code.upper()

    for index, play in enumerate(plays):
        context = _PlayContext(
            index=index,
            league_code=code,
            home_abbr=home_abbr,
            away_abbr=away_abbr,
            final_index=final_index,
            run_enders=run_enders,
        )
        _enrich_play(play, context)


def validate_detail_contract(plays: list[PlayEntry]) -> None:
    """Fail closed if the stream is not fully renderable by v2 clients."""
    for index, play in enumerate(plays):
        prefix = f"play[{index}]"
        if play.mode_eligibility is None:
            raise DetailContractError(f"{prefix}.modeEligibility missing")
        if play.mode_eligibility.all is not True:
            raise DetailContractError(f"{prefix}.modeEligibility.all must be true")
        if play.importance is None:
            raise DetailContractError(f"{prefix}.importance missing")
        if not (play.display_type or "").strip():
            raise DetailContractError(f"{prefix}.displayType missing")
        if not (play.period_label or "").strip():
            raise DetailContractError(f"{prefix}.periodLabel missing")


def display_type_for(raw_type: str | None) -> str:
    """Return a customer-facing play type label."""
    key = _normalize_type(raw_type)
    if not key:
        return "Other play"
    if key in _DISPLAY_LABELS:
        return _DISPLAY_LABELS[key]
    cleaned = re.sub(r"[_-]+", " ", key).strip()
    if not cleaned:
        return "Other play"
    return cleaned.capitalize()


def _enrich_play(play: PlayEntry, context: _PlayContext) -> None:
    raw_type = _normalize_type(play.play_type)
    play.display_type = display_type_for(play.play_type)
    play.clock_label = play.time_label or play.game_clock
    play.period_label = play.period_label or _fallback_period_label(play)
    play.score_after = play.score

    score_before = play.score_before
    score_after = play.score
    is_scoring = play.score_changed is True
    if is_scoring and score_before and score_after:
        play.score_display = _score_display(score_after, context)

    is_lead_change = _is_lead_change(score_before, score_after)
    is_tying = _is_tying_play(score_before, score_after)
    is_late = play.phase in {"late", "ot"} or _late_period(play.quarter, context.league_code)
    is_final = play.play_index == context.final_index
    is_run_ending = play.play_index in context.run_enders
    is_close = _score_margin(score_after) <= _close_margin(context.league_code)
    reasons: list[str] = []

    if is_scoring:
        reasons.append("scoring")
    if is_lead_change:
        reasons.append("lead-change")
    if is_tying:
        reasons.append("tying-play")
    if is_late:
        reasons.append("late-game")
    if is_final:
        reasons.append("final-play")
    if is_run_ending:
        reasons.append("run-ending")

    tier = play.tier or 3
    if tier == 2:
        reasons.append("notable")

    primary = _is_primary_play(
        raw_type=raw_type,
        is_scoring=is_scoring,
        is_lead_change=is_lead_change,
        is_tying=is_tying,
        is_late=is_late,
        is_close=is_close,
        is_final=is_final,
        is_run_ending=is_run_ending,
        tier=tier,
        league_code=context.league_code,
    )
    secondary = primary or is_scoring or tier <= 2

    level = "primary" if primary else ("secondary" if secondary else "tertiary")
    rank = _rank(
        level=level,
        is_lead_change=is_lead_change,
        is_tying=is_tying,
        is_final=is_final,
        is_late=is_late,
        is_close=is_close,
        is_scoring=is_scoring,
        tier=tier,
    )
    play.importance = PlayImportance(
        level=level,
        rank=rank,
        reasons=reasons,
        isKeyMoment=primary,
        isScoringPlay=is_scoring,
        isLeadChange=is_lead_change,
        isTyingPlay=is_tying,
        isLateGame=is_late,
        isFinalPlay=is_final,
        isRunEnding=is_run_ending,
    )
    play.mode_eligibility = PlayModeEligibility(
        important=primary,
        standard=secondary,
        all=True,
    )


def _is_primary_play(
    *,
    raw_type: str,
    is_scoring: bool,
    is_lead_change: bool,
    is_tying: bool,
    is_late: bool,
    is_close: bool,
    is_final: bool,
    is_run_ending: bool,
    tier: int,
    league_code: str,
) -> bool:
    if is_lead_change or is_tying or is_final or is_run_ending:
        return True

    if league_code == "MLB":
        if is_scoring:
            return True
        if raw_type in _MLB_THREAT_ENDING_TYPES:
            return True
        if is_late and is_close and tier <= 2:
            return True
        return False

    if league_code in {"NBA", "NCAAB"}:
        if is_late and is_close and (is_scoring or raw_type in _POSSESSION_SWING_TYPES or tier <= 2):
            return True
        return False

    if league_code == "NHL":
        if is_scoring and raw_type != "empty_net_goal":
            return True
        if is_late and is_close and tier <= 2:
            return True
        return False

    if league_code in {"NFL", "NCAAF"}:
        if is_scoring:
            return True
        if raw_type in _POSSESSION_SWING_TYPES:
            return True
        if is_late and is_close and tier <= 2:
            return True
        return False

    return is_scoring or (is_late and is_close and tier <= 2)


def _detect_run_ending_plays(plays: list[PlayEntry]) -> set[int]:
    run_enders: set[int] = set()
    scorer: str | None = None
    run_total = 0
    last_play: int | None = None

    for play in plays:
        before = play.score_before
        after = play.score
        if not before or not after:
            continue
        home_delta = after.home - before.home
        away_delta = after.away - before.away
        current_scorer: str | None = None
        points = 0
        if home_delta > 0 and away_delta == 0:
            current_scorer = "home"
            points = home_delta
        elif away_delta > 0 and home_delta == 0:
            current_scorer = "away"
            points = away_delta
        else:
            continue

        if current_scorer == scorer:
            run_total += points
            last_play = play.play_index
        else:
            if run_total >= 6 and last_play is not None:
                run_enders.add(last_play)
            scorer = current_scorer
            run_total = points
            last_play = play.play_index

    if run_total >= 6 and last_play is not None:
        run_enders.add(last_play)
    return run_enders


def _rank(
    *,
    level: str,
    is_lead_change: bool,
    is_tying: bool,
    is_final: bool,
    is_late: bool,
    is_close: bool,
    is_scoring: bool,
    tier: int,
) -> int:
    if level == "tertiary":
        return 10
    score = 50 if level == "primary" else 25
    if is_lead_change:
        score += 35
    if is_tying:
        score += 30
    if is_final:
        score += 25
    if is_late:
        score += 15
    if is_close:
        score += 10
    if is_scoring:
        score += 8
    if tier == 2:
        score += 4
    return min(score, 100)


def _normalize_type(raw_type: str | None) -> str:
    return (raw_type or "").strip().lower().replace(" ", "_").replace("-", "_")


def _fallback_period_label(play: PlayEntry) -> str:
    if play.quarter is not None:
        return f"Period {play.quarter}"
    return f"Play {play.play_index}"


def _leader(score: ScoreObject | None) -> int:
    if score is None:
        return 0
    if score.home > score.away:
        return 1
    if score.away > score.home:
        return -1
    return 0


def _is_lead_change(before: ScoreObject | None, after: ScoreObject | None) -> bool:
    before_leader = _leader(before)
    after_leader = _leader(after)
    return before_leader != 0 and after_leader != 0 and before_leader != after_leader


def _is_tying_play(before: ScoreObject | None, after: ScoreObject | None) -> bool:
    if before is None or after is None:
        return False
    return before.home != before.away and after.home == after.away


def _score_margin(score: ScoreObject | None) -> int:
    if score is None:
        return 999
    return abs(score.home - score.away)


def _close_margin(league_code: str) -> int:
    return {
        "MLB": 2,
        "NBA": 8,
        "NCAAB": 8,
        "NHL": 1,
        "NFL": 8,
        "NCAAF": 8,
    }.get(league_code, 4)


def _late_period(period: int | None, league_code: str) -> bool:
    if period is None:
        return False
    return period >= {
        "MLB": 7,
        "NBA": 4,
        "NCAAB": 2,
        "NHL": 3,
        "NFL": 4,
        "NCAAF": 4,
    }.get(league_code, 4)


def _score_display(score: ScoreObject, context: _PlayContext) -> str | None:
    if not context.away_abbr or not context.home_abbr:
        return None
    return f"{context.away_abbr} {score.away} · {context.home_abbr} {score.home}"


__all__ = [
    "DetailContractError",
    "display_type_for",
    "enrich_play_importance",
    "validate_detail_contract",
]
