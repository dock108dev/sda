"""MLB per-game processing functions.

See game_processors.py for the shared GameProcessResult dataclass and
public dispatcher API.
"""

from __future__ import annotations

from ..logging import logger
from .game_processors import (
    GameProcessResult,
    live_pbp_payload_unchanged,
    should_create_live_pbp_snapshot,
    try_promote_to_live,
)


def check_game_status_mlb(session, game, *, client=None) -> GameProcessResult:
    """Check MLB schedule for status transitions and score updates."""
    from ..db import db_models
    from ..live.mlb import MLBLiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..utils.datetime_utils import now_utc, to_et_date

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        return GameProcessResult()

    try:
        mlb_game_id = int(mlb_game_pk)
    except (ValueError, TypeError):
        return GameProcessResult()

    if client is None:
        client = MLBLiveFeedClient()
    result = GameProcessResult()

    game_day = to_et_date(game.game_date) if game.game_date else None
    if not game_day:
        return result

    schedule_games = client.fetch_schedule(game_day, game_day)
    result.api_calls += 1

    for sg in schedule_games:
        if sg.game_pk == mlb_game_id:
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
                    league="MLB",
                    from_status=old_status,
                    to_status=new_status,
                )

            if sg.home_score is not None:
                game.home_score = sg.home_score
            if sg.away_score is not None:
                game.away_score = sg.away_score
            break

    return result


def process_game_pbp_mlb(session, game, *, client=None, live_poll: bool = False) -> GameProcessResult:
    """Fetch and persist PBP for a single MLB game."""
    from ..live.mlb import MLBLiveFeedClient
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        return GameProcessResult()

    try:
        mlb_game_id = int(mlb_game_pk)
    except (ValueError, TypeError):
        return GameProcessResult()

    if client is None:
        client = MLBLiveFeedClient()
    result = GameProcessResult()

    payload = client.fetch_play_by_play(mlb_game_id, game_status=game.status)
    result.api_calls += 1

    if payload.plays:
        if live_poll and live_pbp_payload_unchanged("MLB", game.id, payload.plays):
            return result

        upsert_kwargs = {"source": "mlb_api"}
        if live_poll:
            upsert_kwargs["create_snapshot"] = should_create_live_pbp_snapshot("MLB", game.id)

        inserted = upsert_plays(
            session,
            game.id,
            payload.plays,
            **upsert_kwargs,
        )
        result.events_inserted = inserted or 0
        game.last_pbp_at = now_utc()

        try_promote_to_live(game, payload.plays, result, "MLB")

    return result


def process_game_boxscore_mlb(session, game, *, client=None) -> GameProcessResult:
    """Fetch and persist boxscore for a single MLB game."""
    from ..live.mlb import MLBLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        return GameProcessResult()

    try:
        mlb_game_id = int(mlb_game_pk)
    except (ValueError, TypeError):
        return GameProcessResult()

    if client is None:
        client = MLBLiveFeedClient()
    result = GameProcessResult()

    boxscore = client.fetch_boxscore(mlb_game_id, game_status=game.status)
    result.api_calls = 1

    if boxscore:
        if boxscore.team_boxscores:
            upsert_team_boxscores(
                session, game.id, boxscore.team_boxscores, source="mlb_api",
            )
        if boxscore.player_boxscores:
            upsert_player_boxscores(
                session, game.id, boxscore.player_boxscores, source="mlb_api",
            )
        game.last_boxscore_at = now_utc()
        result.boxscore_updated = True

        logger.info(
            "poll_mlb_boxscore_ok",
            game_id=game.id,
            teams=len(boxscore.team_boxscores),
            players=len(boxscore.player_boxscores),
        )

    return result
