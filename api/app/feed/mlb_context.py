"""MLB context adapter for normalized narrative cards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.sports import SportsGame, SportsGamePlay
from app.routers.sports.schemas.common import ScoreObject
from app.scroll_down_mlb._state_readers import read_count, read_count_before, read_str
from app.scroll_down_mlb.game_state import compute_timeline
from app.scroll_down_mlb.internal_types import TimelineEntry

from .schemas import ScoreChange


@dataclass(frozen=True)
class MlbCardContext:
    """Deterministic MLB situation context for one normalized card."""

    summary: str
    raw: dict[str, Any]
    score_before: ScoreObject
    score_after: ScoreObject
    score_change: ScoreChange
    impact: str


def build_mlb_card_contexts(
    game: SportsGame,
    sorted_plays: list[SportsGamePlay],
) -> dict[int, MlbCardContext]:
    """Build MLB card contexts from the shared MLB timeline reconstruction."""
    home_abbr = game.home_team.abbreviation if game.home_team else None
    timeline_plays = [_timeline_play(play) for play in sorted_plays]
    frames = compute_timeline(timeline_plays, home_abbr)
    by_index = {play["playIndex"]: play for play in timeline_plays}
    return {
        play_index: _context_from_frame(frame, by_index.get(play_index, {}))
        for play_index, frame in frames.items()
    }


def _timeline_play(play: SportsGamePlay) -> dict[str, Any]:
    raw_data = play.raw_data if isinstance(play.raw_data, dict) else {}
    payload = dict(raw_data)
    team_abbr = play.team.abbreviation if play.team else raw_data.get("team_abbreviation")
    payload.update(
        {
            "playIndex": play.play_index,
            "quarter": play.quarter,
            "playType": play.play_type,
            "description": play.description,
            "teamAbbreviation": team_abbr,
            "playerName": play.player_name,
        }
    )
    if play.home_score is not None or play.away_score is not None:
        payload["score"] = {"home": play.home_score or 0, "away": play.away_score or 0}
        payload["homeScore"] = play.home_score
        payload["awayScore"] = play.away_score
    return payload


def _context_from_frame(frame: TimelineEntry, play: dict[str, Any]) -> MlbCardContext:
    score_change = ScoreChange(
        home=max(0, frame.score_after_home - frame.score_before_home),
        away=max(0, frame.score_after_away - frame.score_before_away),
    )
    score_before = ScoreObject(home=frame.score_before_home, away=frame.score_before_away)
    score_after = ScoreObject(home=frame.score_after_home, away=frame.score_after_away)
    impact = _score_impact(frame)
    summary = _summary(frame, impact)
    raw = {
        "schemaVersion": 1,
        "sport": "mlb",
        "period": {
            "ordinal": frame.inning,
            "phase": frame.half,
            "label": _inning_label(frame.inning, frame.half),
        },
        "score": {
            "before": score_before.model_dump(mode="json"),
            "change": score_change.model_dump(mode="json"),
            "impact": impact,
        },
        "baseOut": {
            "outsBefore": frame.outs_before,
            "outsAfter": frame.outs_after,
            "basesBefore": dict(frame.base_state_before),
            "basesAfter": dict(frame.base_state_after),
            "baseStateBefore": _base_state_label(frame.base_state_before),
            "baseStateAfter": _base_state_label(frame.base_state_after),
            "runnerNamesBefore": dict(frame.runner_names_before),
            "runnerNamesAfter": dict(frame.runner_names_after),
            "strandedRunners": _stranded_runners(frame),
        },
        "matchup": {
            "batterName": _batter_name(play),
            "pitcherName": _pitcher_name(play),
            "count": _count(play),
        },
        "result": {
            "eventType": frame.event_type,
            "description": play.get("description"),
            "runsScored": frame.runs_scored,
        },
        "flags": {
            "isScoringPlay": frame.is_scoring_play,
            "isTyingPlay": frame.is_tying_play,
            "isLeadChange": frame.is_lead_change_play,
            "isGoAhead": _is_go_ahead(frame),
            "isInningEnding": frame.outs_after >= 3,
        },
        "source": "scroll_down_mlb.compute_timeline",
    }
    return MlbCardContext(
        summary=summary,
        raw=raw,
        score_before=score_before,
        score_after=score_after,
        score_change=score_change,
        impact=impact,
    )


def _score_impact(frame: TimelineEntry) -> str:
    if frame.is_lead_change_play:
        return "lead_change"
    if frame.is_tying_play:
        return "tying"
    if _is_go_ahead(frame):
        return "go_ahead"
    if frame.is_scoring_play:
        return "scoring"
    return "none"


def _is_go_ahead(frame: TimelineEntry) -> bool:
    if not frame.is_scoring_play:
        return False
    before = _leader(frame.score_before_home, frame.score_before_away)
    after = _leader(frame.score_after_home, frame.score_after_away)
    return after != "tie" and before != after


def _leader(home: int, away: int) -> str:
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "tie"


def _summary(frame: TimelineEntry, impact: str) -> str:
    pieces = [
        _inning_label(frame.inning, frame.half),
        _outs_label(frame.outs_before),
        _base_state_label(frame.base_state_before),
    ]
    if impact != "none":
        pieces.append(impact.replace("_", " "))
    return ", ".join(piece for piece in pieces if piece)


def _inning_label(inning: int, half: str) -> str:
    return f"{half.title()} {inning}"


def _outs_label(outs: int) -> str:
    if outs == 1:
        return "1 out"
    return f"{outs} outs"


def _base_state_label(bases: dict[str, bool]) -> str:
    occupied = [
        label
        for key, label in (("first", "1st"), ("second", "2nd"), ("third", "3rd"))
        if bases.get(key)
    ]
    return "Runners on " + " and ".join(occupied) if occupied else "Bases empty"


def _stranded_runners(frame: TimelineEntry) -> list[str]:
    if frame.outs_after < 3:
        return []
    source = frame.runner_names_after or frame.runner_names_before
    return [
        source.get(base) or base
        for base in ("first", "second", "third")
        if frame.base_state_after.get(base) or frame.base_state_before.get(base)
    ]


def _batter_name(play: dict[str, Any]) -> str | None:
    batter = play.get("batter")
    return read_str(
        play.get("batterName"),
        batter.get("name") if isinstance(batter, dict) else None,
        play.get("playerName"),
    )


def _pitcher_name(play: dict[str, Any]) -> str | None:
    pitcher = play.get("pitcher")
    return read_str(
        play.get("pitcherName"),
        pitcher.get("name") if isinstance(pitcher, dict) else None,
    )


def _count(play: dict[str, Any]) -> dict[str, int] | None:
    count = read_count_before(play) or read_count(play)
    if count is None:
        return None
    return {"balls": count[0], "strikes": count[1]}

