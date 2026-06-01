"""Basketball context adapter for normalized narrative cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.db.sports import SportsGame
from app.routers.sports.schemas.common import PlayEntry, ScoreObject
from app.services.pipeline.stages.league_config import get_config, get_flow_thresholds

from .schemas import ScoreChange
from .value_helpers import drop_empty, normalize_type


@dataclass(frozen=True)
class BasketballCardContext:
    """Deterministic basketball situation context for one normalized card."""

    summary: str
    raw: dict[str, Any]
    score_before: ScoreObject
    score_after: ScoreObject
    score_change: ScoreChange
    impact: str


@dataclass(frozen=True)
class _RunState:
    team: str
    points_for: int
    points_against: int
    start_play_index: int
    end_play_index: int
    start_score: ScoreObject
    end_score: ScoreObject


def build_basketball_card_contexts(
    game: SportsGame,
    plays: list[PlayEntry],
) -> dict[int, BasketballCardContext]:
    """Build NBA/NCAAB card contexts from enriched play snapshots."""
    league = (game.league.code if game.league else "NBA").upper()
    home_abbr = game.home_team.abbreviation if game.home_team else None
    away_abbr = game.away_team.abbreviation if game.away_team else None
    runs = _run_contexts(plays, league)
    return {
        play.play_index: _context_from_play(
            play,
            league=league,
            home_abbr=home_abbr,
            away_abbr=away_abbr,
            run=runs.get(play.play_index),
        )
        for play in plays
    }


def _context_from_play(
    play: PlayEntry,
    *,
    league: str,
    home_abbr: str | None,
    away_abbr: str | None,
    run: dict[str, Any] | None,
) -> BasketballCardContext:
    config = get_config(league)
    thresholds = get_flow_thresholds(league)
    score_before = play.score_before or ScoreObject(home=0, away=0)
    score_after = play.score_after or play.score or score_before
    score_change = ScoreChange(
        home=max(0, score_after.home - score_before.home),
        away=max(0, score_after.away - score_before.away),
    )
    lead = _lead_context(score_before, score_after)
    clutch = _clutch_context(
        play=play,
        score_after=score_after,
        config=config,
        thresholds=thresholds,
    )
    result = _play_result(play)
    impact = _score_impact(score_change, lead=lead, clutch=clutch, run=run)
    raw = {
        "schemaVersion": 1,
        "sport": "basketball",
        "period": {
            "ordinal": play.quarter,
            "label": play.period_label,
            "type": play.period_type,
            "unit": config["period_noun"],
        },
        "clock": {
            "label": play.time_label or play.clock_label or play.game_clock,
            "gameClock": play.game_clock,
            "secondsRemaining": _clock_seconds_remaining(play.game_clock),
        },
        "score": {
            "before": score_before.model_dump(mode="json"),
            "change": score_change.model_dump(mode="json"),
            "impact": impact,
            "marginBefore": abs(score_before.home - score_before.away),
            "marginAfter": abs(score_after.home - score_after.away),
        },
        "lead": lead,
        "run": run,
        "clutch": clutch,
        "result": result,
        "flags": {
            "isScoringPlay": bool(score_change.home or score_change.away),
            "isLeadChange": bool(lead["isLeadChange"]),
            "isTyingPlay": bool(lead["isTyingPlay"]),
            "isGoAheadPlay": bool(lead["isGoAheadPlay"]),
            "isClutch": bool(clutch["isClutch"]),
            "isRunEnding": bool(run and run.get("isRunEnding")),
        },
        "source": "sda_basketball_rules",
    }
    summary = _summary(play, impact=impact, run=run, clutch=clutch)
    return BasketballCardContext(
        summary=summary,
        raw=drop_empty(raw),
        score_before=score_before,
        score_after=score_after,
        score_change=score_change,
        impact=impact,
    )


def _run_contexts(plays: list[PlayEntry], league: str) -> dict[int, dict[str, Any]]:
    thresholds = get_flow_thresholds(league)
    min_points = int(thresholds["scoring_run_pts"])
    max_against = int(thresholds["scoring_run_opp_pts"])
    by_play: dict[int, dict[str, Any]] = {}
    state: _RunState | None = None

    def finalize(candidate: _RunState | None) -> None:
        if candidate is None:
            return
        if candidate.points_for < min_points or candidate.points_against > max_against:
            return
        label = f"{candidate.points_for}-{candidate.points_against} {candidate.team} run"
        by_play[candidate.end_play_index] = {
            "team": candidate.team,
            "pointsFor": candidate.points_for,
            "pointsAgainst": candidate.points_against,
            "startPlayIndex": candidate.start_play_index,
            "endPlayIndex": candidate.end_play_index,
            "startScore": candidate.start_score.model_dump(mode="json"),
            "endScore": candidate.end_score.model_dump(mode="json"),
            "isRunEnding": True,
            "label": label,
            "thresholdPoints": min_points,
        }

    for play in plays:
        before = play.score_before
        after = play.score_after or play.score
        if before is None or after is None:
            continue
        home_delta = after.home - before.home
        away_delta = after.away - before.away
        if home_delta < 0 or away_delta < 0 or (home_delta > 0 and away_delta > 0):
            finalize(state)
            state = None
            continue
        scoring_team = None
        points = 0
        if home_delta > 0 and away_delta == 0:
            scoring_team = "home"
            points = home_delta
        elif away_delta > 0 and home_delta == 0:
            scoring_team = "away"
            points = away_delta
        if scoring_team is None:
            continue
        if state is not None and state.team == scoring_team:
            state = _RunState(
                team=state.team,
                points_for=state.points_for + points,
                points_against=state.points_against,
                start_play_index=state.start_play_index,
                end_play_index=play.play_index,
                start_score=state.start_score,
                end_score=after,
            )
            continue
        finalize(state)
        state = _RunState(
            team=scoring_team,
            points_for=points,
            points_against=0,
            start_play_index=play.play_index,
            end_play_index=play.play_index,
            start_score=before,
            end_score=after,
        )

    finalize(state)
    return by_play


def _lead_context(before: ScoreObject, after: ScoreObject) -> dict[str, Any]:
    leader_before = _leader(before)
    leader_after = _leader(after)
    return {
        "leaderBefore": leader_before,
        "leaderAfter": leader_after,
        "marginBefore": abs(before.home - before.away),
        "marginAfter": abs(after.home - after.away),
        "isLeadChange": (
            leader_before in {"home", "away"}
            and leader_after in {"home", "away"}
            and leader_before != leader_after
        ),
        "isTyingPlay": leader_before in {"home", "away"} and leader_after == "tied",
        "isGoAheadPlay": leader_before == "tied" and leader_after in {"home", "away"},
    }


def _leader(score: ScoreObject) -> str:
    if score.home > score.away:
        return "home"
    if score.away > score.home:
        return "away"
    return "tied"


def _clutch_context(
    *,
    play: PlayEntry,
    score_after: ScoreObject,
    config: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    seconds_remaining = _clock_seconds_remaining(play.game_clock)
    period = play.quarter
    regulation_periods = int(config["regulation_periods"])
    threshold_seconds = int(thresholds["clutch_window_minutes"]) * 60
    threshold_points = int(thresholds["clutch_window_pts"])
    margin = abs(score_after.home - score_after.away)
    in_overtime = bool(period is not None and period > regulation_periods)
    final_period_window = bool(
        period == regulation_periods
        and seconds_remaining is not None
        and seconds_remaining <= threshold_seconds
    )
    close = margin <= threshold_points
    is_clutch = close and (in_overtime or final_period_window)
    reason = None
    if is_clutch:
        reason = "overtime_close" if in_overtime else "final_5_close"
    return {
        "isClutch": is_clutch,
        "reason": reason,
        "secondsRemainingInPeriod": seconds_remaining,
        "margin": margin,
        "thresholdPoints": threshold_points,
        "thresholdSeconds": threshold_seconds,
    }


def _play_result(play: PlayEntry) -> dict[str, Any]:
    raw_type = normalize_type(play.play_type)
    result: dict[str, Any] = {
        "type": raw_type or "unknown",
        "displayType": play.display_type,
        "description": play.description,
        "family": _result_family(raw_type),
    }
    if raw_type in {"3pt", "3pt_made", "three_point", "three_point_made"}:
        result["threePoint"] = {"made": True, "points": 3}
    if raw_type in {"free_throw", "freethrow"}:
        result["freeThrow"] = {"made": bool(play.score_changed)}
    if raw_type in {"timeout", "team_timeout", "official_timeout"}:
        result["timeout"] = {"type": raw_type}
    if "foul" in raw_type:
        result["foul"] = {"type": raw_type}
    and_one = _explicit_bool(play, "and_one", "andOne")
    if and_one is not None:
        result["andOne"] = and_one
    return drop_empty(result)


def _result_family(raw_type: str) -> str:
    if raw_type in {
        "made_shot",
        "layup",
        "dunk",
        "2pt",
        "2pt_made",
        "3pt",
        "3pt_made",
        "three_point",
        "three_point_made",
        "free_throw",
        "freethrow",
    }:
        return "score"
    if "foul" in raw_type:
        return "foul"
    if "timeout" in raw_type:
        return "timeout"
    if raw_type in {"turnover", "steal"}:
        return "turnover"
    if "rebound" in raw_type:
        return "rebound"
    if raw_type in {"block", "missed_shot", "missed_2pt", "missed_3pt"}:
        return "miss"
    return "unknown"


def _score_impact(
    score_change: ScoreChange,
    *,
    lead: dict[str, Any],
    clutch: dict[str, Any],
    run: dict[str, Any] | None,
) -> str:
    if lead["isLeadChange"]:
        return "lead_change"
    if lead["isTyingPlay"]:
        return "tying"
    if lead["isGoAheadPlay"]:
        return "go_ahead"
    if run and run.get("isRunEnding"):
        return "scoring_run"
    if (score_change.home or score_change.away) and clutch["isClutch"]:
        return "clutch_score"
    if score_change.home or score_change.away:
        return "scoring"
    return "none"


def _summary(
    play: PlayEntry,
    *,
    impact: str,
    run: dict[str, Any] | None,
    clutch: dict[str, Any],
) -> str:
    pieces = [play.time_label or play.period_label or play.clock_label]
    if run and run.get("label"):
        pieces.append(str(run["label"]))
    elif impact != "none":
        pieces.append(impact.replace("_", " "))
    if clutch["isClutch"]:
        pieces.append("clutch window")
    return ", ".join(piece for piece in pieces if piece) or "Basketball play"


def _clock_seconds_remaining(clock: str | None) -> int | None:
    if not clock:
        return None
    match = re.match(r"^\s*(\d{1,2}):(\d{2})(?:\.\d+)?\s*$", clock)
    if not match:
        return None
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    return minutes * 60 + seconds


def _explicit_bool(play: PlayEntry, *keys: str) -> bool | None:
    for source in (play.metadata, play.sport_metadata):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, bool):
                return value
    return None
