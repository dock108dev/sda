"""Polling helper functions for live game data (NBA/NHL per-game).

NBA and NHL use per-game API calls for scoreboard, PBP, and boxscores.
NCAAB batch polling lives in polling_helpers_ncaab.py.

These are called by the @shared_task entry points in polling_tasks.py.

All per-game processing logic lives in services.game_processors (SSOT).
This module wraps those functions with error handling and 429 detection.
"""

from __future__ import annotations

from ..logging import logger

# Shared constants (also defined in polling_tasks.py for task-level use)
_JITTER_MIN = 1.0
_JITTER_MAX = 2.0


class _RateLimitError(Exception):
    """Raised when an API returns 429."""


def _should_fetch_pbp(game, status_result) -> bool:
    """Determine if PBP should be fetched for this game.

    Fetches PBP when the game is live/pregame, OR when the game just
    transitioned to final in this poll cycle.  The latter ensures we
    capture the complete PBP (including the final scoring play) before
    the game is marked as done.
    """
    from ..db import db_models

    if game.status in (db_models.GameStatus.live.value, db_models.GameStatus.pregame.value):
        return True

    # If the game just went final in this cycle, do one last PBP fetch
    if (
        status_result
        and status_result.transition
        and status_result.transition.get("to") == db_models.GameStatus.final.value
    ):
        return True

    return False


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
    elif league_code == "NFL":
        result = _poll_nfl_game(session, game)
    elif league_code == "NCAAB":
        pass  # Handled by _poll_ncaab_games_batch

    return result


def _poll_nba_game(session, game) -> dict:
    """Poll a single NBA game via the NBA live API."""
    from ..db import db_models
    from ..live.nba import NBALiveFeedClient
    from ..services.game_processors import (
        check_game_status_nba,
        process_game_pbp_nba,
    )

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        logger.debug("poll_nba_skip_no_game_id", game_id=game.id)
        return {"api_calls": 0}

    client = NBALiveFeedClient()
    result: dict = {"api_calls": 0}
    status_result = None

    # Fetch scoreboard for status check
    try:
        status_result = check_game_status_nba(session, game, client=client)
        result["api_calls"] += status_result.api_calls
        if status_result.transition:
            result["transition"] = status_result.transition
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nba_scoreboard_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live, pregame, or just transitioned to final
    if _should_fetch_pbp(game, status_result):
        try:
            pbp_result = process_game_pbp_nba(session, game, client=client)
            result["api_calls"] += pbp_result.api_calls
            if pbp_result.events_inserted:
                result["pbp_events"] = pbp_result.events_inserted
            if pbp_result.transition:
                result["transition"] = pbp_result.transition
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_nba_pbp_error", game_id=game.id, error=str(exc))

    return result


def _poll_nhl_game(session, game) -> dict:
    """Poll a single NHL game via the NHL live API."""
    from ..db import db_models
    from ..live.nhl import NHLLiveFeedClient
    from ..services.game_processors import (
        check_game_status_nhl,
        process_game_pbp_nhl,
    )

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        logger.debug("poll_nhl_skip_no_game_pk", game_id=game.id)
        return {"api_calls": 0}

    try:
        int(nhl_game_pk)
    except (ValueError, TypeError):
        logger.warning("poll_nhl_invalid_game_pk", game_id=game.id, nhl_game_pk=nhl_game_pk)
        return {"api_calls": 0}

    client = NHLLiveFeedClient()
    result: dict = {"api_calls": 0}
    status_result = None

    # Fetch schedule for status check
    try:
        status_result = check_game_status_nhl(session, game, client=client)
        result["api_calls"] += status_result.api_calls
        if status_result.transition:
            result["transition"] = status_result.transition
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nhl_schedule_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live, pregame, or just transitioned to final
    if _should_fetch_pbp(game, status_result):
        try:
            pbp_result = process_game_pbp_nhl(session, game, client=client)
            result["api_calls"] += pbp_result.api_calls
            if pbp_result.events_inserted:
                result["pbp_events"] = pbp_result.events_inserted
            if pbp_result.transition:
                result["transition"] = pbp_result.transition
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_nhl_pbp_error", game_id=game.id, error=str(exc))

    return result


def _poll_mlb_game(session, game) -> dict:
    """Poll a single MLB game via the MLB Stats API."""
    from ..db import db_models
    from ..live.mlb import MLBLiveFeedClient
    from ..services.game_processors import (
        check_game_status_mlb,
        process_game_pbp_mlb,
    )

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        logger.debug("poll_mlb_skip_no_game_pk", game_id=game.id)
        return {"api_calls": 0}

    try:
        int(mlb_game_pk)
    except (ValueError, TypeError):
        logger.warning("poll_mlb_invalid_game_pk", game_id=game.id, mlb_game_pk=mlb_game_pk)
        return {"api_calls": 0}

    client = MLBLiveFeedClient()
    result: dict = {"api_calls": 0}
    status_result = None

    # Fetch schedule for status check
    try:
        status_result = check_game_status_mlb(session, game, client=client)
        result["api_calls"] += status_result.api_calls
        if status_result.transition:
            result["transition"] = status_result.transition
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_mlb_schedule_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live, pregame, or just transitioned to final
    if _should_fetch_pbp(game, status_result):
        try:
            pbp_result = process_game_pbp_mlb(session, game, client=client)
            result["api_calls"] += pbp_result.api_calls
            if pbp_result.events_inserted:
                result["pbp_events"] = pbp_result.events_inserted
            if pbp_result.transition:
                result["transition"] = pbp_result.transition
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_mlb_pbp_error", game_id=game.id, error=str(exc))

    return result


def _poll_nfl_game(session, game) -> dict:
    """Poll a single NFL game via the ESPN API."""
    from ..db import db_models
    from ..live.nfl import NFLLiveFeedClient
    from ..services.game_processors import (
        check_game_status_nfl,
        process_game_pbp_nfl,
    )

    espn_game_id = (game.external_ids or {}).get("espn_game_id")
    if not espn_game_id:
        logger.debug("poll_nfl_skip_no_game_id", game_id=game.id)
        return {"api_calls": 0}

    try:
        int(espn_game_id)
    except (ValueError, TypeError):
        logger.warning("poll_nfl_invalid_game_id", game_id=game.id, espn_game_id=espn_game_id)
        return {"api_calls": 0}

    client = NFLLiveFeedClient()
    result: dict = {"api_calls": 0}
    status_result = None

    # Fetch scoreboard for status check
    try:
        status_result = check_game_status_nfl(session, game, client=client)
        result["api_calls"] += status_result.api_calls
        if status_result.transition:
            result["transition"] = status_result.transition
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nfl_schedule_error", game_id=game.id, error=str(exc))

    # Fetch PBP if game is live, pregame, or just transitioned to final
    if _should_fetch_pbp(game, status_result):
        try:
            pbp_result = process_game_pbp_nfl(session, game, client=client)
            result["api_calls"] += pbp_result.api_calls
            if pbp_result.events_inserted:
                result["pbp_events"] = pbp_result.events_inserted
            if pbp_result.transition:
                result["transition"] = pbp_result.transition
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning("poll_nfl_pbp_error", game_id=game.id, error=str(exc))

    return result


# ---------------------------------------------------------------------------
# Boxscore polling helpers (NBA / NHL / MLB / NFL)
# ---------------------------------------------------------------------------


def _poll_nba_game_boxscore(session, game) -> dict:
    """Fetch and persist boxscore for a single live NBA game."""
    from ..services.game_processors import process_game_boxscore_nba

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        return {"api_calls": 0}

    try:
        r = process_game_boxscore_nba(session, game)
        return {
            "api_calls": r.api_calls,
            "boxscore_updated": r.boxscore_updated,
        }
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nba_boxscore_error", game_id=game.id, error=str(exc))
        return {"api_calls": 0, "boxscore_updated": False}


def _poll_nhl_game_boxscore(session, game) -> dict:
    """Fetch and persist boxscore for a single live NHL game."""
    from ..services.game_processors import process_game_boxscore_nhl

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        return {"api_calls": 0}

    try:
        int(nhl_game_pk)
    except (ValueError, TypeError):
        return {"api_calls": 0}

    try:
        r = process_game_boxscore_nhl(session, game)
        return {
            "api_calls": r.api_calls,
            "boxscore_updated": r.boxscore_updated,
        }
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_nhl_boxscore_error", game_id=game.id, error=str(exc))
        return {"api_calls": 0, "boxscore_updated": False}


def _poll_mlb_game_boxscore(session, game) -> dict:
    """Fetch and persist boxscore for a single live MLB game."""
    from ..services.game_processors import process_game_boxscore_mlb

    mlb_game_pk = (game.external_ids or {}).get("mlb_game_pk")
    if not mlb_game_pk:
        return {"api_calls": 0}

    try:
        int(mlb_game_pk)
    except (ValueError, TypeError):
        return {"api_calls": 0}

    try:
        r = process_game_boxscore_mlb(session, game)
        return {
            "api_calls": r.api_calls,
            "boxscore_updated": r.boxscore_updated,
        }
    except Exception as exc:
        if "429" in str(exc):
            raise _RateLimitError() from exc
        logger.warning("poll_mlb_boxscore_error", game_id=game.id, error=str(exc))
        return {"api_calls": 0, "boxscore_updated": False}
