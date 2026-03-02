"""Polling helper functions for live game data (NBA/NHL per-game).

NBA and NHL use per-game API calls for scoreboard, PBP, and boxscores.
NCAAB batch polling lives in polling_helpers_ncaab.py.

These are called by the @shared_task entry points in polling_tasks.py.
"""

from __future__ import annotations

from ..logging import logger

# Shared constants (also defined in polling_tasks.py for task-level use)
_JITTER_MIN = 1.0
_JITTER_MAX = 2.0


class _RateLimitError(Exception):
    """Raised when an API returns 429."""


def _poll_single_game_pbp(session, game) -> dict:
    """Poll a single game for status + PBP updates.

    Returns dict with api_calls count, transition info, and pbp_events.
    NCAAB games are handled by _poll_ncaab_games_batch and skipped here.
    """
    from ..db import db_models

    league = session.query(db_models.SportsLeague).get(game.league_id)
    if not league:
        return {"api_calls": 0}

    league_code = league.code
    result: dict = {"api_calls": 0}

    if league_code == "NBA":
        result = _poll_nba_game(session, game)
    elif league_code == "NHL":
        result = _poll_nhl_game(session, game)
    elif league_code == "MLB":
        result = _poll_mlb_game(session, game)
    elif league_code == "NCAAB":
        pass  # Handled by _poll_ncaab_games_batch

    return result


def _poll_nba_game(session, game) -> dict:
    """Poll a single NBA game via the NBA live API."""
    from ..db import db_models
    from ..live.nba import NBALiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        logger.debug("poll_nba_skip_no_game_id", game_id=game.id)
        return {"api_calls": 0}

    client = NBALiveFeedClient()
    result: dict = {"api_calls": 0}

    # Fetch scoreboard for status check
    try:
        game_day = game.game_date.date() if game.game_date else None
        if game_day:
            scoreboard_games = client.fetch_scoreboard(game_day)
            result["api_calls"] += 1

            # Find this game in the scoreboard
            for sg in scoreboard_games:
                if sg.game_id == nba_game_id:
                    # Check for status transition
                    new_status = resolve_status_transition(game.status, sg.status)
                    if new_status != game.status:
                        old_status = game.status
                        game.status = new_status
                        game.updated_at = now_utc()

                        # Set end_time when transitioning to final
                        if new_status == db_models.GameStatus.final.value and game.end_time is None:
                            game.end_time = now_utc()

                        result["transition"] = {
                            "game_id": game.id,
                            "from": old_status,
                            "to": new_status,
                        }
                        logger.info(
                            "poll_pbp_status_transition",
                            game_id=game.id,
                            league="NBA",
                            from_status=old_status,
                            to_status=new_status,
                        )

                    # Update scores
                    if sg.home_score is not None:
                        game.home_score = sg.home_score
                    if sg.away_score is not None:
                        game.away_score = sg.away_score
                    break
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nba_scoreboard_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live or pregame (not for games that just went final)
    if game.status in (db_models.GameStatus.live.value, db_models.GameStatus.pregame.value):
        try:
            payload = client.fetch_play_by_play(nba_game_id)
            result["api_calls"] += 1

            if payload.plays:
                inserted = upsert_plays(session, game.id, payload.plays, source="nba_api")
                result["pbp_events"] = inserted
                game.last_pbp_at = now_utc()

                # Infer live if PBP has plays but game is still pregame
                if game.status == db_models.GameStatus.pregame.value:
                    game.status = db_models.GameStatus.live.value
                    game.updated_at = now_utc()
                    result["transition"] = {
                        "game_id": game.id,
                        "from": "pregame",
                        "to": "live",
                    }
                    logger.info(
                        "poll_pbp_inferred_live",
                        game_id=game.id,
                        league="NBA",
                        reason="pbp_plays_found",
                        play_count=len(payload.plays),
                    )
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_nba_pbp_error", game_id=game.id, error=str(exc))

    return result


def _poll_nhl_game(session, game) -> dict:
    """Poll a single NHL game via the NHL live API."""
    from ..db import db_models
    from ..live.nhl import NHLLiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        logger.debug("poll_nhl_skip_no_game_pk", game_id=game.id)
        return {"api_calls": 0}

    try:
        nhl_game_id = int(nhl_game_pk)
    except (ValueError, TypeError):
        logger.warning("poll_nhl_invalid_game_pk", game_id=game.id, nhl_game_pk=nhl_game_pk)
        return {"api_calls": 0}

    client = NHLLiveFeedClient()
    result: dict = {"api_calls": 0}

    # Fetch schedule for status check
    try:
        game_day = game.game_date.date() if game.game_date else None
        if game_day:
            schedule_games = client.fetch_schedule(game_day, game_day)
            result["api_calls"] += 1

            for sg in schedule_games:
                if sg.game_id == nhl_game_id:
                    new_status = resolve_status_transition(game.status, sg.status)
                    if new_status != game.status:
                        old_status = game.status
                        game.status = new_status
                        game.updated_at = now_utc()

                        if new_status == db_models.GameStatus.final.value and game.end_time is None:
                            game.end_time = now_utc()

                        result["transition"] = {
                            "game_id": game.id,
                            "from": old_status,
                            "to": new_status,
                        }
                        logger.info(
                            "poll_pbp_status_transition",
                            game_id=game.id,
                            league="NHL",
                            from_status=old_status,
                            to_status=new_status,
                        )

                    if sg.home_score is not None:
                        game.home_score = sg.home_score
                    if sg.away_score is not None:
                        game.away_score = sg.away_score
                    break
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nhl_schedule_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live or pregame
    if game.status in (db_models.GameStatus.live.value, db_models.GameStatus.pregame.value):
        try:
            payload = client.fetch_play_by_play(nhl_game_id)
            result["api_calls"] += 1

            if payload.plays:
                inserted = upsert_plays(session, game.id, payload.plays, source="nhl_api")
                result["pbp_events"] = inserted
                game.last_pbp_at = now_utc()

                # Infer live if PBP has plays but game is still pregame
                if game.status == db_models.GameStatus.pregame.value:
                    game.status = db_models.GameStatus.live.value
                    game.updated_at = now_utc()
                    result["transition"] = {
                        "game_id": game.id,
                        "from": "pregame",
                        "to": "live",
                    }
                    logger.info(
                        "poll_pbp_inferred_live",
                        game_id=game.id,
                        league="NHL",
                        reason="pbp_plays_found",
                        play_count=len(payload.plays),
                    )
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_nhl_pbp_error", game_id=game.id, error=str(exc))

    return result


def _poll_mlb_game(session, game) -> dict:
    """Poll a single MLB game via the MLB Stats API."""
    from ..db import db_models
    from ..live.mlb import MLBLiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        logger.debug("poll_mlb_skip_no_game_pk", game_id=game.id)
        return {"api_calls": 0}

    try:
        mlb_game_id = int(mlb_game_pk)
    except (ValueError, TypeError):
        logger.warning("poll_mlb_invalid_game_pk", game_id=game.id, mlb_game_pk=mlb_game_pk)
        return {"api_calls": 0}

    client = MLBLiveFeedClient()
    result: dict = {"api_calls": 0}

    # Fetch schedule for status check
    try:
        game_day = game.game_date.date() if game.game_date else None
        if game_day:
            schedule_games = client.fetch_schedule(game_day, game_day)
            result["api_calls"] += 1

            for sg in schedule_games:
                if sg.game_pk == mlb_game_id:
                    new_status = resolve_status_transition(game.status, sg.status)
                    if new_status != game.status:
                        old_status = game.status
                        game.status = new_status
                        game.updated_at = now_utc()

                        if new_status == db_models.GameStatus.final.value and game.end_time is None:
                            game.end_time = now_utc()

                        result["transition"] = {
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
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_mlb_schedule_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live or pregame
    if game.status in (db_models.GameStatus.live.value, db_models.GameStatus.pregame.value):
        try:
            payload = client.fetch_play_by_play(mlb_game_id, game_status=game.status)
            result["api_calls"] += 1

            if payload.plays:
                inserted = upsert_plays(session, game.id, payload.plays, source="mlb_api")
                result["pbp_events"] = inserted
                game.last_pbp_at = now_utc()

                # Infer live if PBP has plays but game is still pregame
                if game.status == db_models.GameStatus.pregame.value:
                    game.status = db_models.GameStatus.live.value
                    game.updated_at = now_utc()
                    result["transition"] = {
                        "game_id": game.id,
                        "from": "pregame",
                        "to": "live",
                    }
                    logger.info(
                        "poll_pbp_inferred_live",
                        game_id=game.id,
                        league="MLB",
                        reason="pbp_plays_found",
                        play_count=len(payload.plays),
                    )
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_mlb_pbp_error", game_id=game.id, error=str(exc))

    return result


# ---------------------------------------------------------------------------
# Boxscore polling helpers (NBA / NHL / MLB)
# ---------------------------------------------------------------------------


def _poll_nba_game_boxscore(session, game) -> dict:
    """Fetch and persist boxscore for a single live NBA game."""
    from ..live.nba import NBALiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        return {"api_calls": 0}

    client = NBALiveFeedClient()
    result: dict = {"api_calls": 0, "boxscore_updated": False}

    try:
        boxscore = client.fetch_boxscore(nba_game_id)
        result["api_calls"] = 1

        if boxscore:
            if boxscore.team_boxscores:
                upsert_team_boxscores(
                    session, game.id, boxscore.team_boxscores, source="nba_api",
                )
            if boxscore.player_boxscores:
                upsert_player_boxscores(
                    session, game.id, boxscore.player_boxscores, source="nba_api",
                )
            game.last_boxscore_at = now_utc()
            result["boxscore_updated"] = True

            logger.info(
                "poll_nba_boxscore_ok",
                game_id=game.id,
                teams=len(boxscore.team_boxscores),
                players=len(boxscore.player_boxscores),
            )
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nba_boxscore_error", game_id=game.id, error=str(exc))

    return result


def _poll_nhl_game_boxscore(session, game) -> dict:
    """Fetch and persist boxscore for a single live NHL game."""
    from ..live.nhl import NHLLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        return {"api_calls": 0}

    try:
        nhl_game_id = int(nhl_game_pk)
    except (ValueError, TypeError):
        return {"api_calls": 0}

    client = NHLLiveFeedClient()
    result: dict = {"api_calls": 0, "boxscore_updated": False}

    try:
        boxscore = client.fetch_boxscore(nhl_game_id)
        result["api_calls"] = 1

        if boxscore:
            if boxscore.team_boxscores:
                upsert_team_boxscores(
                    session, game.id, boxscore.team_boxscores, source="nhl_api",
                )
            if boxscore.player_boxscores:
                upsert_player_boxscores(
                    session, game.id, boxscore.player_boxscores, source="nhl_api",
                )
            game.last_boxscore_at = now_utc()
            result["boxscore_updated"] = True

            logger.info(
                "poll_nhl_boxscore_ok",
                game_id=game.id,
                teams=len(boxscore.team_boxscores),
                players=len(boxscore.player_boxscores),
            )
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nhl_boxscore_error", game_id=game.id, error=str(exc))

    return result


def _poll_mlb_game_boxscore(session, game) -> dict:
    """Fetch and persist boxscore for a single live MLB game."""
    from ..live.mlb import MLBLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        return {"api_calls": 0}

    try:
        mlb_game_id = int(mlb_game_pk)
    except (ValueError, TypeError):
        return {"api_calls": 0}

    client = MLBLiveFeedClient()
    result: dict = {"api_calls": 0, "boxscore_updated": False}

    try:
        boxscore = client.fetch_boxscore(mlb_game_id, game_status=game.status)
        result["api_calls"] = 1

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
            result["boxscore_updated"] = True

            logger.info(
                "poll_mlb_boxscore_ok",
                game_id=game.id,
                teams=len(boxscore.team_boxscores),
                players=len(boxscore.player_boxscores),
            )
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_mlb_boxscore_error", game_id=game.id, error=str(exc))

    return result
