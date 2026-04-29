"""NFL per-game processing functions.

See game_processors.py for the shared GameProcessResult dataclass and
public dispatcher API.
"""

from __future__ import annotations

from ..logging import logger
from .game_processors import GameProcessResult, try_promote_to_live


def check_game_status_nfl(session, game, *, client=None) -> GameProcessResult:
    """Check ESPN scoreboard for NFL status transitions and score updates."""
    from ..db import db_models
    from ..live.nfl import NFLLiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..utils.datetime_utils import now_utc, to_et_date

    espn_game_id = (game.external_ids or {}).get("espn_game_id")
    if not espn_game_id:
        return GameProcessResult()

    try:
        espn_id = int(espn_game_id)
    except (ValueError, TypeError):
        return GameProcessResult()

    if client is None:
        client = NFLLiveFeedClient()
    result = GameProcessResult()

    game_day = to_et_date(game.game_date) if game.game_date else None
    if not game_day:
        return result

    schedule_games = client.fetch_schedule(game_day, game_day)
    result.api_calls += 1

    for sg in schedule_games:
        if sg.game_id == espn_id:
            new_status = resolve_status_transition(game.status, sg.status)
            if new_status != game.status:
                old_status = game.status
                game.status = new_status
                game.updated_at = now_utc()

                if new_status == db_models.GameStatus.final.value and game.end_time is None:
                    game.end_time = now_utc()

                result.transition = {
                    "game_id": game.id,
                    "from": old_status,
                    "to": new_status,
                }
                logger.info(
                    "poll_pbp_status_transition",
                    game_id=game.id,
                    league="NFL",
                    from_status=old_status,
                    to_status=new_status,
                )

            if sg.home_score is not None:
                game.home_score = sg.home_score
            if sg.away_score is not None:
                game.away_score = sg.away_score
            break

    return result


def process_game_pbp_nfl(session, game, *, client=None) -> GameProcessResult:
    """Fetch and persist PBP for a single NFL game."""
    from ..live.nfl import NFLLiveFeedClient
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    espn_game_id = (game.external_ids or {}).get("espn_game_id")
    if not espn_game_id:
        return GameProcessResult()

    try:
        espn_id = int(espn_game_id)
    except (ValueError, TypeError):
        return GameProcessResult()

    if client is None:
        client = NFLLiveFeedClient()
    result = GameProcessResult()

    payload = client.fetch_play_by_play(espn_id)
    result.api_calls += 1

    if payload.plays:
        inserted = upsert_plays(session, game.id, payload.plays, source="espn_nfl_api")
        result.events_inserted = inserted or 0
        game.last_pbp_at = now_utc()

        try_promote_to_live(game, payload.plays, result, "NFL")

    return result


def process_game_boxscore_nfl(session, game, *, client=None) -> GameProcessResult:
    """Fetch and persist boxscore for a single NFL game."""
    from ..live.nfl import NFLLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    espn_game_id = (game.external_ids or {}).get("espn_game_id")
    if not espn_game_id:
        return GameProcessResult()

    try:
        espn_id = int(espn_game_id)
    except (ValueError, TypeError):
        return GameProcessResult()

    if client is None:
        client = NFLLiveFeedClient()
    result = GameProcessResult()

    boxscore = client.fetch_boxscore(espn_id)
    result.api_calls = 1

    if boxscore:
        if boxscore.team_boxscores:
            upsert_team_boxscores(
                session, game.id, boxscore.team_boxscores, source="espn_nfl_api",
            )
        if boxscore.player_boxscores:
            upsert_player_boxscores(
                session, game.id, boxscore.player_boxscores, source="espn_nfl_api",
            )
        game.last_boxscore_at = now_utc()
        result.boxscore_updated = True

        logger.info(
            "poll_nfl_boxscore_ok",
            game_id=game.id,
            teams=len(boxscore.team_boxscores),
            players=len(boxscore.player_boxscores),
        )

    return result
