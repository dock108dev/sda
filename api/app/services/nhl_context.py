"""NHL context helpers for play serialization and narrative cards."""

from __future__ import annotations

from typing import Any, Literal

TeamSide = Literal["home", "away"]


def decode_nhl_situation_code(value: Any) -> dict[str, Any] | None:
    """Decode NHL API situationCode into skater and goalie counts.

    The NHL API encodes away goalie count, away skaters, home skaters, and home
    goalie count as four digits. Values outside that shape are treated as
    unknown instead of guessed.
    """
    code = str(value or "").strip()
    if len(code) != 4 or not code.isdigit():
        return None

    away_goalies = int(code[0])
    away_skaters = int(code[1])
    home_skaters = int(code[2])
    home_goalies = int(code[3])
    pulled_sides = [
        side
        for side, goalies in (("away", away_goalies), ("home", home_goalies))
        if goalies == 0
    ]
    return _drop_empty(
        {
            "situationCode": code,
            "skaters": {"away": away_skaters, "home": home_skaters},
            "goalies": {"away": away_goalies, "home": home_goalies},
            "goaliePulled": bool(pulled_sides),
            "goaliePulledSides": pulled_sides,
            "manpowerState": (
                "even_strength" if away_skaters == home_skaters else "uneven_strength"
            ),
            "skaterDifferential": home_skaters - away_skaters,
        }
    )


def classify_nhl_strength(
    decoded: dict[str, Any] | None,
    *,
    event_side: TeamSide | None,
) -> str | None:
    """Return the event team's strength state when the side is known."""
    if not decoded:
        return None
    skaters = decoded.get("skaters")
    if not isinstance(skaters, dict):
        return None
    home = _int_or_none(skaters.get("home"))
    away = _int_or_none(skaters.get("away"))
    if home is None or away is None:
        return None
    if event_side is None:
        return "even_strength" if home == away else "special_teams"
    event_count = home if event_side == "home" else away
    opponent_count = away if event_side == "home" else home
    if event_count > opponent_count:
        return "power_play"
    if event_count < opponent_count:
        return "penalty_kill"
    return "even_strength"


def nhl_event_context(raw_data: dict[str, Any], play_type: str | None) -> dict[str, Any]:
    """Promote stable NHL goal, penalty, and shot fields from raw details."""
    details = raw_data.get("details")
    details = details if isinstance(details, dict) else {}
    normalized_type = _normalize_type(play_type or raw_data.get("type_desc_key"))
    shot_type = _str_or_none(details.get("shotType"))
    assists = _assist_player_ids(details)
    penalty_duration = _int_or_none(details.get("duration"))
    penalty_type = _str_or_none(details.get("descKey"), details.get("typeCode"))
    empty_net = _bool_or_none(details.get("emptyNet"), details.get("isEmptyNet"))
    context = {
        "eventType": normalized_type,
        "sourceType": _str_or_none(raw_data.get("type_desc_key")),
        "shotType": shot_type,
        "zone": _str_or_none(details.get("zoneCode")),
        "xCoord": _number_or_none(details.get("xCoord")),
        "yCoord": _number_or_none(details.get("yCoord")),
        "assistPlayerIds": assists,
        "penaltyType": penalty_type,
        "penaltyDurationMinutes": penalty_duration,
        "committedByPlayerId": _id_or_none(details.get("committedByPlayerId")),
        "drawnByPlayerId": _id_or_none(details.get("drawnByPlayerId")),
        "shootingPlayerId": _id_or_none(details.get("shootingPlayerId")),
        "scoringPlayerId": _id_or_none(details.get("scoringPlayerId")),
        "goalieInNetId": _id_or_none(details.get("goalieInNetId")),
        "emptyNet": empty_net,
        "isGoal": normalized_type == "goal",
        "isPenalty": normalized_type == "penalty",
        "isSaveContext": normalized_type in {"shot_on_goal", "save"},
    }
    return _drop_empty(context)


def build_nhl_play_situation(
    *,
    raw_data: dict[str, Any],
    period_ordinal: int | None,
    period_label: str | None,
    clock_label: str | None,
    team_abbr: str | None,
    player_name: str | None,
    play_type: str | None,
) -> dict[str, Any] | None:
    """Build a structured hockey situation snapshot for a serialized play."""
    decoded = decode_nhl_situation_code(raw_data.get("situation_code"))
    event = nhl_event_context(raw_data, play_type)
    strength = classify_nhl_strength(decoded, event_side=None)
    hockey = _drop_empty(
        {
            **(decoded or {}),
            "strengthState": strength,
            "shotType": event.get("shotType"),
            "assistPlayerIds": event.get("assistPlayerIds"),
            "emptyNet": event.get("emptyNet"),
            "penaltyType": event.get("penaltyType"),
            "penaltyDurationMinutes": event.get("penaltyDurationMinutes"),
            "eventType": event.get("eventType"),
        }
    )
    if not any([decoded, event, period_ordinal, clock_label, team_abbr, player_name]):
        return None
    headline = _headline(period_label, clock_label, strength)
    return _drop_empty(
        {
            "schemaVersion": 1,
            "sport": "nhl",
            "display": _drop_empty({"headline": headline}),
            "period": _drop_empty(
                {
                    "ordinal": period_ordinal,
                    "label": period_label,
                    "type": _str_or_none(raw_data.get("period_type")),
                }
            ),
            "clock": _drop_empty(
                {
                    "label": clock_label,
                    "timeRemaining": _str_or_none(raw_data.get("time_remaining")),
                    "timeInPeriod": _str_or_none(raw_data.get("time_in_period")),
                }
            ),
            "possession": _drop_empty({"teamAbbreviation": team_abbr}),
            "actor": _drop_empty({"playerName": player_name}),
            "sportState": {"hockey": hockey} if hockey else None,
            "event": event,
            "confidence": {
                "level": "high" if decoded else "medium",
                "source": "nhl_api",
            },
        }
    )


def nhl_consumer_play_metadata(raw_data: dict[str, Any]) -> dict[str, Any] | None:
    """Return compact NHL metadata safe for consumer clients."""
    decoded = decode_nhl_situation_code(raw_data.get("situation_code"))
    event = nhl_event_context(raw_data, raw_data.get("type_desc_key"))
    strength = classify_nhl_strength(decoded, event_side=None)
    metadata = _drop_empty(
        {
            "situationCode": raw_data.get("situation_code"),
            "strengthState": strength,
            "goaliePulled": (decoded or {}).get("goaliePulled"),
            "goaliePulledSides": (decoded or {}).get("goaliePulledSides"),
            "shotType": event.get("shotType"),
            "assistPlayerIds": event.get("assistPlayerIds"),
            "emptyNet": event.get("emptyNet"),
            "penaltyType": event.get("penaltyType"),
            "penaltyDurationMinutes": event.get("penaltyDurationMinutes"),
        }
    )
    return metadata or None


def clock_seconds_remaining(clock: str | None) -> int | None:
    """Convert an NHL MM:SS clock value to seconds remaining in the period."""
    if not isinstance(clock, str) or ":" not in clock:
        return None
    minutes_text, seconds_text = clock.split(":", 1)
    try:
        minutes = int(minutes_text)
        seconds = int(seconds_text)
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds >= 60:
        return None
    return minutes * 60 + seconds


def is_late_close_nhl_time(
    *,
    period: int | None,
    clock: str | None,
    score_margin: int | None,
) -> bool:
    """Return true for late third-period or overtime close-game NHL context."""
    if period is None:
        return False
    if period > 3:
        return True
    seconds = clock_seconds_remaining(clock)
    return bool(period == 3 and seconds is not None and seconds <= 300 and (score_margin or 0) <= 1)


def _headline(period_label: str | None, clock_label: str | None, strength: str | None) -> str | None:
    pieces = [period_label, clock_label]
    if strength and strength != "even_strength":
        pieces.append(strength.replace("_", " "))
    return ", ".join(piece for piece in pieces if piece)


def _assist_player_ids(details: dict[str, Any]) -> list[str]:
    ids = [
        _id_or_none(details.get("assist1PlayerId")),
        _id_or_none(details.get("assist2PlayerId")),
    ]
    return [player_id for player_id in ids if player_id]


def _normalize_type(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _id_or_none(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(int(value))
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _number_or_none(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    return None


def _str_or_none(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _bool_or_none(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: nested
        for key, nested in value.items()
        if nested is not None and nested != {} and nested != []
    }
