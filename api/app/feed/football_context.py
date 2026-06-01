"""Football context adapter for normalized narrative cards."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.db.sports import SportsGame, SportsGamePlay
from app.routers.sports.schemas.common import PlayEntry, ScoreObject

from .schemas import ScoreChange
from .value_helpers import drop_empty, normalize_type


@dataclass(frozen=True)
class FootballCardContext:
    """Deterministic football drive context for one normalized card."""

    summary: str
    raw: dict[str, Any]
    score_before: ScoreObject
    score_after: ScoreObject
    score_change: ScoreChange
    impact: str
    source_play_id: str | None = None


def build_football_card_contexts(
    game: SportsGame,
    plays: list[PlayEntry],
    sorted_plays: list[SportsGamePlay],
) -> dict[int, FootballCardContext]:
    """Build NFL/NCAAF card contexts from available play source fields."""
    league = (game.league.code if game.league else "NFL").upper()
    raw_by_index = {
        play.play_index: play.raw_data
        for play in sorted_plays
        if isinstance(play.raw_data, dict)
    }
    return {
        play.play_index: _context_from_play(
            play,
            league=league,
            raw_data=raw_by_index.get(play.play_index) or {},
        )
        for play in plays
    }


def _context_from_play(
    play: PlayEntry,
    *,
    league: str,
    raw_data: dict[str, Any],
) -> FootballCardContext:
    score_before = play.score_before or ScoreObject(home=0, away=0)
    score_after = play.score_after or play.score or score_before
    score_change = ScoreChange(
        home=max(0, score_after.home - score_before.home),
        away=max(0, score_after.away - score_before.away),
    )
    source = _source_fields(raw_data)
    field_position = _field_position(source.yard_line)
    result = _play_result(play, raw_data=raw_data, source=source)
    flags = _flags(
        play=play,
        source=source,
        field_position=field_position,
        score_change=score_change,
        result=result,
    )
    impact = _score_impact(play, score_change, flags=flags)
    raw = {
        "schemaVersion": 1,
        "sport": "football",
        "league": league,
        "period": {
            "ordinal": play.quarter,
            "label": play.period_label,
            "type": play.period_type,
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
        "drive": _drive_context(play, source=source, field_position=field_position),
        "result": result,
        "flags": flags,
        "source": "football_source_fields" if source.has_drive_context else "score_timeline",
    }
    return FootballCardContext(
        summary=_summary(play, source=source, field_position=field_position, impact=impact, flags=flags),
        raw=drop_empty(raw),
        score_before=score_before,
        score_after=score_after,
        score_change=score_change,
        impact=impact,
        source_play_id=source.espn_play_id,
    )


@dataclass(frozen=True)
class _SourceFields:
    down: int | None
    distance: int | None
    yard_line: int | None
    yards: int | None
    scoring_play: bool | None
    espn_play_id: str | None
    play_type_id: str | None
    play_type_text: str | None

    @property
    def has_drive_context(self) -> bool:
        return any(
            value is not None
            for value in (self.down, self.distance, self.yard_line, self.yards, self.play_type_text)
        )


def _source_fields(raw_data: dict[str, Any]) -> _SourceFields:
    return _SourceFields(
        down=_int_value(raw_data.get("start_down"), raw_data.get("startDown"), raw_data.get("down")),
        distance=_int_value(
            raw_data.get("start_distance"),
            raw_data.get("startDistance"),
            raw_data.get("distance"),
            raw_data.get("yardsToGo"),
        ),
        yard_line=_yard_line_value(
            raw_data.get("start_yard_line"),
            raw_data.get("startYardLine"),
            raw_data.get("yardLine"),
            raw_data.get("yard_line"),
            raw_data.get("field_position"),
        ),
        yards=_int_value(raw_data.get("yards"), raw_data.get("statYardage"), raw_data.get("yardage")),
        scoring_play=_bool_value(raw_data.get("scoring_play"), raw_data.get("scoringPlay")),
        espn_play_id=_str_value(raw_data.get("espn_play_id"), raw_data.get("espnPlayId")),
        play_type_id=_str_value(raw_data.get("play_type_id"), raw_data.get("playTypeId")),
        play_type_text=_str_value(raw_data.get("play_type_text"), raw_data.get("playTypeText")),
    )


def _drive_context(
    play: PlayEntry,
    *,
    source: _SourceFields,
    field_position: dict[str, Any] | None,
) -> dict[str, Any]:
    if not source.has_drive_context and field_position is None:
        return {}
    down_distance = _down_distance_text(source.down, source.distance)
    return drop_empty(
        {
            "possessionTeam": play.team_abbreviation,
            "down": source.down,
            "distance": source.distance,
            "downDistance": down_distance,
            "yardLine": source.yard_line,
            "fieldPosition": field_position,
            "yardsGained": source.yards,
            "stakes": _drive_stakes(source=source, field_position=field_position),
        }
    )


def _play_result(
    play: PlayEntry,
    *,
    raw_data: dict[str, Any],
    source: _SourceFields,
) -> dict[str, Any]:
    raw_type = normalize_type(source.play_type_text or play.play_type)
    return drop_empty(
        {
            "type": normalize_type(play.play_type) or "unknown",
            "displayType": play.display_type,
            "description": play.description,
            "playTypeText": source.play_type_text,
            "playTypeId": source.play_type_id,
            "espnPlayId": source.espn_play_id,
            "yards": source.yards,
            "scoringPlay": source.scoring_play,
            "family": _result_family(raw_type),
            "driveSource": raw_data.get("drive_id") or raw_data.get("driveId"),
        }
    )


def _flags(
    *,
    play: PlayEntry,
    source: _SourceFields,
    field_position: dict[str, Any] | None,
    score_change: ScoreChange,
    result: dict[str, Any],
) -> dict[str, bool]:
    normalized = " ".join(
        value
        for value in (
            normalize_type(play.play_type),
            normalize_type(source.play_type_text),
            normalize_type(play.description),
        )
        if value
    )
    is_scoring = bool(source.scoring_play or score_change.home or score_change.away)
    is_turnover = _is_turnover(normalized)
    is_fourth_down = source.down == 4
    fourth_conversion = bool(
        is_fourth_down
        and not is_turnover
        and not _is_kicking_result(result["type"])
        and (
            is_scoring
            or (
                source.yards is not None
                and source.distance is not None
                and source.yards >= source.distance
            )
        )
    )
    fourth_stop = bool(
        is_fourth_down
        and not fourth_conversion
        and (
            is_turnover
            or "turnover_on_downs" in normalized
            or result["type"] in {"punt", "field_goal_missed", "missed_field_goal"}
            or (
                source.yards is not None
                and source.distance is not None
                and source.yards < source.distance
            )
        )
    )
    return {
        "isRedZone": bool(field_position and field_position.get("isRedZone")),
        "isTurnover": is_turnover,
        "isFourthDown": is_fourth_down,
        "isFourthDownConversion": fourth_conversion,
        "isFourthDownStop": fourth_stop,
        "isExplosivePlay": _is_explosive_play(result["type"], source.yards),
        "isScoringPlay": is_scoring,
        "isLeadChange": bool(play.importance and play.importance.is_lead_change),
        "isTyingPlay": bool(play.importance and play.importance.is_tying_play),
        "isTwoMinuteSituation": _is_two_minute_situation(play),
    }


def _drive_stakes(
    *,
    source: _SourceFields,
    field_position: dict[str, Any] | None,
) -> list[str]:
    stakes: list[str] = []
    if source.down == 4:
        stakes.append("fourth_down")
    if field_position and field_position.get("isRedZone"):
        stakes.append("red_zone")
    if source.distance is not None and source.distance >= 10:
        stakes.append("long_distance")
    if source.distance is not None and source.distance <= 2:
        stakes.append("short_yardage")
    return stakes


def _score_impact(
    play: PlayEntry,
    score_change: ScoreChange,
    *,
    flags: dict[str, bool],
) -> str:
    if flags["isLeadChange"]:
        return "lead_change"
    if flags["isTyingPlay"]:
        return "tying"
    if flags["isScoringPlay"]:
        return "scoring"
    if flags["isTurnover"]:
        return "turnover"
    if flags["isFourthDownStop"]:
        return "fourth_down_stop"
    if flags["isFourthDownConversion"]:
        return "fourth_down_conversion"
    if flags["isExplosivePlay"]:
        return "explosive_play"
    if flags["isRedZone"]:
        return "red_zone"
    if flags["isTwoMinuteSituation"]:
        return "two_minute"
    if score_change.home or score_change.away:
        return "score_change"
    return "none"


def _summary(
    play: PlayEntry,
    *,
    source: _SourceFields,
    field_position: dict[str, Any] | None,
    impact: str,
    flags: dict[str, bool],
) -> str:
    pieces = [play.time_label or play.period_label or play.clock_label]
    down_distance = _down_distance_text(source.down, source.distance)
    if down_distance:
        pieces.append(down_distance)
    if field_position and field_position.get("label"):
        pieces.append(str(field_position["label"]))
    if source.yards is not None:
        pieces.append(f"{source.yards} yards")
    if impact != "none":
        pieces.append(impact.replace("_", " "))
    elif flags["isTwoMinuteSituation"]:
        pieces.append("two minute situation")
    return ", ".join(piece for piece in pieces if piece) or "Football play"


def _field_position(yard_line: int | None) -> dict[str, Any] | None:
    if yard_line is None:
        return None
    clamped = max(0, min(100, yard_line))
    if clamped == 50:
        label = "50"
        side = "midfield"
        yards_to_goal = 50
    elif clamped > 50:
        yards_to_goal = 100 - clamped
        label = f"Opp {yards_to_goal}"
        side = "opponent"
    else:
        yards_to_goal = 100 - clamped
        label = f"Own {clamped}"
        side = "own"
    return {
        "absoluteYardLine": clamped,
        "label": label,
        "side": side,
        "yardsToGoal": yards_to_goal,
        "isRedZone": clamped >= 80,
    }


def _down_distance_text(down: int | None, distance: int | None) -> str | None:
    if down is None:
        return None
    label = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(down, str(down))
    if distance is None:
        return label
    return f"{label} & {distance}"


def _clock_seconds_remaining(clock: str | None) -> int | None:
    if not clock:
        return None
    match = re.match(r"^\s*(\d{1,2}):(\d{2})(?:\.\d+)?\s*$", clock)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _is_two_minute_situation(play: PlayEntry) -> bool:
    normalized = normalize_type(play.play_type)
    if normalized == "two_minute_warning":
        return True
    seconds = _clock_seconds_remaining(play.game_clock)
    return bool(play.quarter in {2, 4} and seconds is not None and seconds <= 120)


def _is_explosive_play(play_type: str, yards: int | None) -> bool:
    if yards is None:
        return False
    if "rush" in play_type:
        return yards >= 10
    if "pass" in play_type or "reception" in play_type:
        return yards >= 20
    return yards >= 20


def _is_turnover(normalized_text: str) -> bool:
    return any(
        marker in normalized_text
        for marker in ("interception", "fumble", "turnover", "picked_off", "lost_ball")
    )


def _is_kicking_result(play_type: str) -> bool:
    return "field_goal" in play_type or play_type in {"punt", "kickoff", "extra_point"}


def _result_family(raw_type: str) -> str:
    if any(marker in raw_type for marker in ("touchdown", "field_goal", "extra_point", "safety")):
        return "score"
    if _is_turnover(raw_type):
        return "turnover"
    if "punt" in raw_type or "kickoff" in raw_type:
        return "special_teams"
    if "penalty" in raw_type:
        return "penalty"
    if "rush" in raw_type:
        return "rush"
    if "pass" in raw_type or "reception" in raw_type or "sack" in raw_type:
        return "pass"
    return "unknown"


def _int_value(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+", value)
            if match:
                return int(match.group(0))
    return None


def _yard_line_value(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, str):
            parsed = _parse_relative_yard_line(value)
            if parsed is not None:
                return parsed
        parsed = _int_value(value)
        if parsed is not None:
            return parsed
    return None


def _parse_relative_yard_line(value: str) -> int | None:
    text = value.strip().lower()
    match = re.search(r"(\d{1,3})", text)
    if not match:
        return None
    yard = int(match.group(1))
    if "opp" in text or "opponent" in text:
        return 100 - yard
    if "own" in text:
        return yard
    return yard


def _bool_value(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _str_value(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None

