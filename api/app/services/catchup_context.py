"""Spoiler-safe game context for catch-up home feeds."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.db.sports import SportsGame, SportsGamePlay, SportsPlayerBoxscore, SportsTeamBoxscore
from app.services.game_status import compute_status_flags
from app.services.openai_client import get_openai_client

logger = logging.getLogger(__name__)

_MAX_CONTEXT_SENTENCES = 3
_OPENAI_SYSTEM_PROMPT = (
    "You write concise, spoiler-safe sports watch notes. Use only the facts provided. "
    "Do not reveal final/current scores, winners, margins, betting odds, or invented injuries. "
    "Return strict JSON only."
)


def _team_name(game: SportsGame, side: str) -> str:
    team = game.home_team if side == "home" else game.away_team
    return team.name if team else ("Home" if side == "home" else "Away")


def _team_abbr(game: SportsGame, side: str) -> str | None:
    team = game.home_team if side == "home" else game.away_team
    return team.abbreviation if team else None


def _league_code(game: SportsGame) -> str:
    return game.league.code if game.league else "UNKNOWN"


def _game_time_label(game: SportsGame) -> str:
    dt = game.game_date
    if not isinstance(dt, datetime):
        return "on the schedule"
    return dt.strftime("%a %b %-d at %-I:%M %p UTC")


def _player_stat_score(
    player: SportsPlayerBoxscore,
    *,
    league_code: str | None = None,
) -> tuple[float, str | None]:
    stats = player.stats or {}
    league = league_code or (_league_code(player.game) if getattr(player, "game", None) else "")

    candidates: list[tuple[str, float, str]] = []
    if league == "MLB" or stats.get("player_role") == "pitcher":
        for key, label in (
            ("strike_outs", "strikeouts"),
            ("strikeouts", "strikeouts"),
            ("hits", "hits"),
            ("rbi", "RBI"),
            ("home_runs", "power"),
        ):
            value = stats.get(key)
            if isinstance(value, int | float):
                candidates.append((key, float(value), label))
    elif league == "NHL" or "shots_on_goal" in stats:
        for key, label in (
            ("points", "points"),
            ("goals", "goals"),
            ("assists", "playmaking"),
            ("shots_on_goal", "shot volume"),
            ("saves", "goaltending"),
        ):
            value = stats.get(key)
            if isinstance(value, int | float):
                candidates.append((key, float(value), label))
    else:
        for key, label in (
            ("points", "scoring"),
            ("assists", "playmaking"),
            ("rebounds", "work on the glass"),
            ("steals", "defense"),
            ("blocks", "rim protection"),
        ):
            value = stats.get(key)
            if isinstance(value, int | float):
                candidates.append((key, float(value), label))

    if not candidates:
        return 0.0, None
    _key, score, label = max(candidates, key=lambda item: item[1])
    return score, label


def _top_player_note(
    players: list[SportsPlayerBoxscore],
    *,
    league_code: str | None = None,
) -> str | None:
    scored: list[tuple[float, str | None, SportsPlayerBoxscore]] = []
    for player in players:
        if not player.player_name:
            continue
        score, label = _player_stat_score(player, league_code=league_code)
        if score > 0:
            scored.append((score, label, player))
    if not scored:
        return None

    _score, label, player = max(scored, key=lambda item: item[0])
    team = player.team.abbreviation or player.team.short_name if player.team else None
    suffix = f" for {label}" if label else ""
    if team:
        return f"{player.player_name} ({team}) is the player-stat thread to follow{suffix}."
    return f"{player.player_name} is the player-stat thread to follow{suffix}."


def _team_stat_note(team_stats: list[SportsTeamBoxscore]) -> str | None:
    if not team_stats:
        return None

    seen: list[str] = []
    label_map = {
        "field_goals": "shooting",
        "fieldGoalPct": "shooting",
        "three_point_field_goals": "three-point shooting",
        "rebounds": "rebounding",
        "turnovers": "turnovers",
        "shots_on_goal": "shot volume",
        "hits": "physicality",
        "faceoff_win_pct": "faceoffs",
        "strikeouts": "strikeouts",
        "base_on_balls": "free passes",
    }
    for box in team_stats:
        for key in box.stats or {}:
            label = label_map.get(str(key))
            if label and label not in seen:
                seen.append(label)
            if len(seen) >= 2:
                break
        if len(seen) >= 2:
            break
    if seen:
        return f"The team-stat layer is useful here for {' and '.join(seen)}."
    return "The team-stat layer is ready if you want the box-score shape after the plays."


def _play_note(plays: list[SportsGamePlay]) -> str | None:
    if not plays:
        return None
    count = len(plays)
    latest = max(plays, key=lambda play: play.play_index)
    if latest.quarter and latest.game_clock:
        return f"There are {count} plays loaded, with the timeline reaching period {latest.quarter} at {latest.game_clock}."
    return f"There are {count} plays loaded, so this is ready for a real scroll-through."


def _base_sentence(game: SportsGame) -> str:
    league = _league_code(game)
    away = _team_name(game, "away")
    home = _team_name(game, "home")
    flags = compute_status_flags(game.status)
    if flags["is_live"]:
        return f"{away} at {home} is live {league} catch-up material, with updates flowing into the play trail."
    if flags["is_final"]:
        return f"{away} at {home} is a completed {league} matchup you can open without seeing the result first."
    return f"{away} at {home} is a {league} matchup coming up {_game_time_label(game)}."


def build_catchup_context(
    game: SportsGame,
    *,
    players: list[SportsPlayerBoxscore] | None = None,
    team_stats: list[SportsTeamBoxscore] | None = None,
    plays: list[SportsGamePlay] | None = None,
) -> list[str]:
    """Build 2-3 spoiler-safe context sentences from local data only."""
    sentences = [_base_sentence(game)]

    game_players = (
        players if players is not None else list(getattr(game, "player_boxscores", []) or [])
    )
    player_note = _top_player_note(game_players, league_code=_league_code(game))
    if player_note:
        sentences.append(player_note)

    game_team_stats = (
        team_stats if team_stats is not None else list(getattr(game, "team_boxscores", []) or [])
    )
    team_note = _team_stat_note(game_team_stats)
    if team_note:
        sentences.append(team_note)

    if len(sentences) < 2:
        game_plays = plays if plays is not None else list(getattr(game, "plays", []) or [])
        play_note = _play_note(game_plays)
        if play_note:
            sentences.append(play_note)

    if len(sentences) < 2:
        away_abbr = _team_abbr(game, "away")
        home_abbr = _team_abbr(game, "home")
        if away_abbr and home_abbr:
            sentences.append(
                f"The matchup gives you a clean {away_abbr}-{home_abbr} filter point for the catch-up feed."
            )
        else:
            sentences.append(
                "The value is the ordered catch-up path: plays first, then player and team stats."
            )

    return sentences[:_MAX_CONTEXT_SENTENCES]


def _openai_prompt(game: SportsGame, context: list[str]) -> str:
    source = {
        "league": _league_code(game),
        "awayTeam": _team_name(game, "away"),
        "homeTeam": _team_name(game, "home"),
        "status": game.status,
        "gameDate": game.game_date.isoformat() if isinstance(game.game_date, datetime) else None,
        "templateContext": context,
    }
    return (
        "Rewrite the source facts into 2 or 3 short homepage sentences explaining why a "
        "user might open this game to catch up. Keep it spoiler-safe. Do not include scores, "
        'winners, margins, or odds. Return JSON like {"context": ["sentence", ...]}.\n\n'
        f"Source facts:\n{json.dumps(source, default=str)}"
    )


def enhance_catchup_context_with_openai(
    game: SportsGame, context: list[str]
) -> tuple[list[str], str]:
    """Optionally polish context through OpenAI; returns fallback on any issue."""
    client = get_openai_client()
    if client is None:
        return context, "template"

    try:
        raw = client.generate(
            prompt=_openai_prompt(game, context),
            temperature=0.4,
            max_tokens=350,
            max_retries=2,
            system_prompt=_OPENAI_SYSTEM_PROMPT,
        )
        parsed = json.loads(raw)
        values = parsed.get("context")
        if not isinstance(values, list):
            raise ValueError("context must be a list")
        sentences = [str(value).strip() for value in values if str(value).strip()]
        if not (2 <= len(sentences) <= _MAX_CONTEXT_SENTENCES):
            raise ValueError("context must contain 2-3 sentences")
        return sentences[:_MAX_CONTEXT_SENTENCES], "openai"
    except Exception as exc:
        logger.warning(
            "catchup_context_openai_failed", extra={"game_id": game.id, "error": str(exc)}
        )
        return context, "template"
