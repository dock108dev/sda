"""NHL context adapter for normalized narrative cards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.sports import SportsGame
from app.routers.sports.schemas.common import PlayEntry, ScoreObject
from app.services.nhl_context import (
    classify_nhl_strength,
    clock_seconds_remaining,
    decode_nhl_situation_code,
    is_late_close_nhl_time,
)

from .schemas import ScoreChange
from .value_helpers import drop_empty, normalize_type_or_none


@dataclass(frozen=True)
class NhlCardContext:
    """Deterministic hockey situation context for one normalized card."""

    summary: str
    raw: dict[str, Any]
    score_before: ScoreObject
    score_after: ScoreObject
    score_change: ScoreChange
    impact: str


def build_nhl_card_contexts(
    game: SportsGame,
    plays: list[PlayEntry],
) -> dict[int, NhlCardContext]:
    """Build NHL card contexts from serialized play situation snapshots."""
    home_abbr = game.home_team.abbreviation if game.home_team else None
    away_abbr = game.away_team.abbreviation if game.away_team else None
    return {
        play.play_index: _context_from_play(play, home_abbr=home_abbr, away_abbr=away_abbr)
        for play in plays
    }


def _context_from_play(
    play: PlayEntry,
    *,
    home_abbr: str | None,
    away_abbr: str | None,
) -> NhlCardContext:
    situation = play.situation_before if isinstance(play.situation_before, dict) else {}
    hockey = _hockey_state(situation)
    event = situation.get("event") if isinstance(situation.get("event"), dict) else {}
    event_side = _team_side(play.team_abbreviation, home_abbr=home_abbr, away_abbr=away_abbr)
    decoded = decode_nhl_situation_code(hockey.get("situationCode"))
    strength = classify_nhl_strength(decoded, event_side=event_side)
    score_before = play.score_before or ScoreObject(home=0, away=0)
    score_after = play.score_after or play.score or score_before
    score_change = ScoreChange(
        home=max(0, score_after.home - score_before.home),
        away=max(0, score_after.away - score_before.away),
    )
    score_margin = abs(score_before.home - score_before.away)
    is_late = is_late_close_nhl_time(
        period=play.quarter,
        clock=play.game_clock,
        score_margin=score_margin,
    )
    empty_net = _empty_net(event, decoded=decoded, event_side=event_side)
    impact = _score_impact(play, score_change, empty_net=empty_net)
    strength_payload = (
        drop_empty(
            {
                "state": strength,
                "manpowerState": hockey.get("manpowerState"),
                "skaters": hockey.get("skaters"),
                "goalies": hockey.get("goalies"),
                "goaliePulled": bool(hockey.get("goaliePulled")),
                "goaliePulledSides": hockey.get("goaliePulledSides"),
                "eventTeamSide": event_side,
                "situationCode": hockey.get("situationCode"),
            }
        )
        if decoded
        else {}
    )
    raw = {
        "schemaVersion": 1,
        "sport": "nhl",
        "period": {
            "ordinal": play.quarter,
            "label": play.period_label,
            "type": play.period_type,
        },
        "clock": {
            "label": play.time_label or play.clock_label or play.game_clock,
            "gameClock": play.game_clock,
            "secondsRemaining": clock_seconds_remaining(play.game_clock),
        },
        "score": {
            "before": score_before.model_dump(mode="json"),
            "change": score_change.model_dump(mode="json"),
            "impact": impact,
        },
        "strength": strength_payload,
        "event": drop_empty(
            {
                "type": event.get("eventType") or normalize_type_or_none(play.play_type),
                "description": play.description,
                "playerName": play.player_name,
                "shotType": event.get("shotType"),
                "assistPlayerIds": event.get("assistPlayerIds"),
                "penaltyType": event.get("penaltyType"),
                "penaltyDurationMinutes": event.get("penaltyDurationMinutes"),
                "emptyNet": empty_net,
                "zone": event.get("zone"),
                "isSaveContext": event.get("isSaveContext"),
            }
        ),
        "flags": {
            "isPowerPlay": strength == "power_play",
            "isPenaltyKill": strength == "penalty_kill",
            "isPowerPlayGoal": _is_goal(play) and strength == "power_play",
            "isPenaltyKillGoal": _is_goal(play) and strength == "penalty_kill",
            "isGoaliePulled": bool(hockey.get("goaliePulled")),
            "isEmptyNet": empty_net,
            "isTyingGoal": bool(play.importance and play.importance.is_tying_play),
            "isLeadChange": bool(play.importance and play.importance.is_lead_change),
            "isLateGame": is_late,
        },
        "source": "nhl_api.situation_code",
    }
    summary = _summary(play, strength=strength, event=event, impact=impact, is_late=is_late)
    return NhlCardContext(
        summary=summary,
        raw=drop_empty(raw),
        score_before=score_before,
        score_after=score_after,
        score_change=score_change,
        impact=impact,
    )


def _hockey_state(situation: dict[str, Any]) -> dict[str, Any]:
    sport_state = situation.get("sportState")
    if not isinstance(sport_state, dict):
        return {}
    hockey = sport_state.get("hockey")
    return hockey if isinstance(hockey, dict) else {}


def _team_side(
    team_abbr: str | None,
    *,
    home_abbr: str | None,
    away_abbr: str | None,
) -> str | None:
    if team_abbr and home_abbr and team_abbr == home_abbr:
        return "home"
    if team_abbr and away_abbr and team_abbr == away_abbr:
        return "away"
    return None


def _score_impact(
    play: PlayEntry,
    score_change: ScoreChange,
    *,
    empty_net: bool,
) -> str:
    if play.importance and play.importance.is_lead_change:
        return "lead_change"
    if play.importance and play.importance.is_tying_play:
        return "tying"
    if score_change.home or score_change.away:
        return "empty_net_goal" if empty_net else "scoring"
    return "none"


def _summary(
    play: PlayEntry,
    *,
    strength: str | None,
    event: dict[str, Any],
    impact: str,
    is_late: bool,
) -> str:
    pieces = [play.time_label or play.period_label or play.clock_label]
    event_text = _event_text(play, event)
    if strength in {"power_play", "penalty_kill"}:
        pieces.append(strength.replace("_", " "))
    if event_text:
        pieces.append(event_text)
    if impact != "none":
        pieces.append(impact.replace("_", " "))
    if is_late:
        pieces.append("late close game")
    return ", ".join(piece for piece in pieces if piece) or "Hockey play"


def _event_text(play: PlayEntry, event: dict[str, Any]) -> str | None:
    normalized_type = event.get("eventType") or normalize_type_or_none(play.play_type)
    if normalized_type == "goal":
        shot_type = event.get("shotType")
        return f"{shot_type} goal" if shot_type else "goal"
    if normalized_type == "penalty":
        duration = event.get("penaltyDurationMinutes")
        penalty_type = event.get("penaltyType")
        if penalty_type and duration:
            return f"{penalty_type} penalty, {duration} min"
        return "penalty"
    if normalized_type in {"shot_on_goal", "save"}:
        shot_type = event.get("shotType")
        return f"{shot_type} save chance" if shot_type else "save chance"
    return play.display_type or play.play_type


def _empty_net(
    event: dict[str, Any],
    *,
    decoded: dict[str, Any] | None,
    event_side: str | None,
) -> bool:
    if event.get("emptyNet") is True:
        return True
    if not decoded or event_side is None:
        return False
    goalies = decoded.get("goalies")
    if not isinstance(goalies, dict):
        return False
    opponent_side = "away" if event_side == "home" else "home"
    return goalies.get(opponent_side) == 0


def _is_goal(play: PlayEntry) -> bool:
    return normalize_type_or_none(play.play_type) == "goal"

