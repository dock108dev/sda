"""SSOT per-game processing functions for all leagues.

Each function takes a session + SportsGame ORM object, fetches data from the
shared API client, calls shared persistence functions, and returns a
GameProcessResult. Functions do NOT handle game selection, rate limiting,
jitter, or locking -- those are caller-side concerns.

Both the live polling path (polling_helpers.py) and the manual/scheduled
ingestion path (pbp_*.py, *_boxscore_ingestion.py) call these same functions,
ensuring identical processing regardless of trigger.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..logging import logger


@dataclass
class GameProcessResult:
    """Result of processing a single game."""

    api_calls: int = 0
    events_inserted: int = 0
    boxscore_updated: bool = False
    transition: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# NBA
# ---------------------------------------------------------------------------


def check_game_status_nba(session, game) -> GameProcessResult:
    """Check NBA scoreboard for status transitions and score updates."""
    from ..db import db_models
    from ..live.nba import NBALiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..utils.datetime_utils import now_utc, to_et_date

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        return GameProcessResult()

    client = NBALiveFeedClient()
    result = GameProcessResult()

    game_day = to_et_date(game.game_date) if game.game_date else None
    if not game_day:
        return result

    scoreboard_games = client.fetch_scoreboard(game_day)
    result.api_calls += 1

    for sg in scoreboard_games:
        if sg.game_id == nba_game_id:
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
                    league="NBA",
                    from_status=old_status,
                    to_status=new_status,
                )

            if sg.home_score is not None:
                game.home_score = sg.home_score
            if sg.away_score is not None:
                game.away_score = sg.away_score
            break

    return result


def process_game_pbp_nba(session, game) -> GameProcessResult:
    """Fetch and persist PBP for a single NBA game."""
    from ..db import db_models
    from ..live.nba import NBALiveFeedClient
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        return GameProcessResult()

    client = NBALiveFeedClient()
    result = GameProcessResult()

    payload = client.fetch_play_by_play(nba_game_id)
    result.api_calls += 1

    if payload.plays:
        inserted = upsert_plays(session, game.id, payload.plays, source="nba_api")
        result.events_inserted = inserted or 0
        game.last_pbp_at = now_utc()

        # Infer live if PBP has plays but game is still pregame
        if game.status == db_models.GameStatus.pregame.value:
            game.status = db_models.GameStatus.live.value
            game.updated_at = now_utc()
            result.transition = {
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

    return result


def process_game_boxscore_nba(session, game) -> GameProcessResult:
    """Fetch and persist boxscore for a single NBA game."""
    from ..live.nba import NBALiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    nba_game_id = (game.external_ids or {}).get("nba_game_id")
    if not nba_game_id:
        return GameProcessResult()

    client = NBALiveFeedClient()
    result = GameProcessResult()

    boxscore = client.fetch_boxscore(nba_game_id)
    result.api_calls = 1

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
        result.boxscore_updated = True

        logger.info(
            "poll_nba_boxscore_ok",
            game_id=game.id,
            teams=len(boxscore.team_boxscores),
            players=len(boxscore.player_boxscores),
        )

    return result


# ---------------------------------------------------------------------------
# NHL
# ---------------------------------------------------------------------------


def check_game_status_nhl(session, game) -> GameProcessResult:
    """Check NHL schedule for status transitions and score updates."""
    from ..db import db_models
    from ..live.nhl import NHLLiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..utils.datetime_utils import now_utc, to_et_date

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        return GameProcessResult()

    try:
        nhl_game_id = int(nhl_game_pk)
    except (ValueError, TypeError):
        return GameProcessResult()

    client = NHLLiveFeedClient()
    result = GameProcessResult()

    game_day = to_et_date(game.game_date) if game.game_date else None
    if not game_day:
        return result

    schedule_games = client.fetch_schedule(game_day, game_day)
    result.api_calls += 1

    for sg in schedule_games:
        if sg.game_id == nhl_game_id:
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
                    league="NHL",
                    from_status=old_status,
                    to_status=new_status,
                )

            if sg.home_score is not None:
                game.home_score = sg.home_score
            if sg.away_score is not None:
                game.away_score = sg.away_score
            break

    return result


def process_game_pbp_nhl(session, game) -> GameProcessResult:
    """Fetch and persist PBP for a single NHL game."""
    from ..db import db_models
    from ..live.nhl import NHLLiveFeedClient
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        return GameProcessResult()

    try:
        nhl_game_id = int(nhl_game_pk)
    except (ValueError, TypeError):
        return GameProcessResult()

    client = NHLLiveFeedClient()
    result = GameProcessResult()

    payload = client.fetch_play_by_play(nhl_game_id)
    result.api_calls += 1

    if payload.plays:
        inserted = upsert_plays(session, game.id, payload.plays, source="nhl_api")
        result.events_inserted = inserted or 0
        game.last_pbp_at = now_utc()

        if game.status == db_models.GameStatus.pregame.value:
            game.status = db_models.GameStatus.live.value
            game.updated_at = now_utc()
            result.transition = {
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

    return result


def process_game_boxscore_nhl(session, game) -> GameProcessResult:
    """Fetch and persist boxscore for a single NHL game."""
    from ..live.nhl import NHLLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
    if not nhl_game_pk:
        return GameProcessResult()

    try:
        nhl_game_id = int(nhl_game_pk)
    except (ValueError, TypeError):
        return GameProcessResult()

    client = NHLLiveFeedClient()
    result = GameProcessResult()

    boxscore = client.fetch_boxscore(nhl_game_id)
    result.api_calls = 1

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
        result.boxscore_updated = True

        logger.info(
            "poll_nhl_boxscore_ok",
            game_id=game.id,
            teams=len(boxscore.team_boxscores),
            players=len(boxscore.player_boxscores),
        )

    return result


# ---------------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------------


def check_game_status_mlb(session, game) -> GameProcessResult:
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


def process_game_pbp_mlb(session, game) -> GameProcessResult:
    """Fetch and persist PBP for a single MLB game."""
    from ..db import db_models
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

    client = MLBLiveFeedClient()
    result = GameProcessResult()

    payload = client.fetch_play_by_play(mlb_game_id, game_status=game.status)
    result.api_calls += 1

    if payload.plays:
        inserted = upsert_plays(session, game.id, payload.plays, source="mlb_api")
        result.events_inserted = inserted or 0
        game.last_pbp_at = now_utc()

        if game.status == db_models.GameStatus.pregame.value:
            game.status = db_models.GameStatus.live.value
            game.updated_at = now_utc()
            result.transition = {
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

    return result


def process_game_boxscore_mlb(session, game) -> GameProcessResult:
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


# ---------------------------------------------------------------------------
# NCAAB
# ---------------------------------------------------------------------------


def process_game_pbp_ncaab(session, game, *, client=None) -> GameProcessResult:
    """Fetch and persist PBP for a single NCAAB game.

    Tries CBB API first (cbb_game_id), then NCAA API fallback (ncaa_game_id).
    """
    from ..db import db_models
    from ..live.ncaab import NCAABLiveFeedClient
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    if client is None:
        client = NCAABLiveFeedClient()

    result = GameProcessResult()
    ext = game.external_ids or {}
    cbb_game_id = ext.get("cbb_game_id")
    ncaa_game_id = ext.get("ncaa_game_id")

    if not cbb_game_id and not ncaa_game_id:
        return result

    # --- Try CBB API first ---
    if cbb_game_id:
        try:
            cbb_id = int(cbb_game_id)
        except (ValueError, TypeError):
            cbb_id = None

        if cbb_id is not None:
            payload = client.fetch_play_by_play(cbb_id, game_status=game.status)
            result.api_calls += 1

            if payload.plays:
                inserted = upsert_plays(session, game.id, payload.plays, source="cbb_api")
                result.events_inserted = inserted or 0
                game.last_pbp_at = now_utc()

                if game.status == db_models.GameStatus.pregame.value:
                    game.status = db_models.GameStatus.live.value
                    game.updated_at = now_utc()
                    result.transition = {
                        "game_id": game.id,
                        "from": "pregame",
                        "to": "live",
                    }
                    logger.info(
                        "poll_pbp_inferred_live",
                        game_id=game.id,
                        league="NCAAB",
                        reason="pbp_plays_found",
                        play_count=len(payload.plays),
                        cbb_game_id=cbb_id,
                    )
                return result

    # --- NCAA API fallback ---
    if ncaa_game_id and result.events_inserted == 0:
        home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
        away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
        home_abbr = home_team.abbreviation if home_team else None
        away_abbr = away_team.abbreviation if away_team else None

        payload = client.fetch_ncaa_play_by_play(
            ncaa_game_id,
            game_status=game.status,
            home_abbr=home_abbr,
            away_abbr=away_abbr,
        )
        result.api_calls += 1

        if payload.plays:
            inserted = upsert_plays(session, game.id, payload.plays, source="ncaa_api")
            result.events_inserted = inserted or 0
            game.last_pbp_at = now_utc()

            if game.status == db_models.GameStatus.pregame.value:
                game.status = db_models.GameStatus.live.value
                game.updated_at = now_utc()
                result.transition = {
                    "game_id": game.id,
                    "from": "pregame",
                    "to": "live",
                }
                logger.info(
                    "poll_pbp_inferred_live",
                    game_id=game.id,
                    league="NCAAB",
                    reason="ncaa_pbp_plays_found",
                    play_count=len(payload.plays),
                    ncaa_game_id=ncaa_game_id,
                )

    return result


def process_game_boxscore_ncaab(session, game, *, client=None) -> GameProcessResult:
    """Fetch and persist boxscore for a single NCAAB game.

    Tries NCAA API per-game boxscore fetch. For batch CBB boxscores, callers
    should use process_game_boxscores_ncaab_batch() instead.
    """
    from ..live.ncaab import NCAABLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.datetime_utils import now_utc

    if client is None:
        client = NCAABLiveFeedClient()

    result = GameProcessResult()
    ext = game.external_ids or {}
    ncaa_game_id = ext.get("ncaa_game_id")

    if not ncaa_game_id:
        return result

    from ..db import db_models

    home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
    away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
    home_name = home_team.name if home_team else "Unknown"
    away_name = away_team.name if away_team else "Unknown"

    boxscore = client.fetch_ncaa_boxscore(
        ncaa_game_id,
        home_team_name=home_name,
        away_team_name=away_name,
        game_status=game.status,
    )
    result.api_calls += 1

    if boxscore:
        if boxscore.team_boxscores:
            upsert_team_boxscores(
                session, game.id, boxscore.team_boxscores,
                source="ncaa_api",
            )
        if boxscore.player_boxscores:
            upsert_player_boxscores(
                session, game.id, boxscore.player_boxscores,
                source="ncaa_api",
            )
        game.last_boxscore_at = now_utc()
        result.boxscore_updated = True

        logger.info(
            "poll_ncaab_boxscore_ok",
            game_id=game.id,
            ncaa_game_id=ncaa_game_id,
            team_stats=len(boxscore.team_boxscores),
            player_stats=len(boxscore.player_boxscores),
        )

    return result


def process_game_boxscores_ncaab_batch(
    session,
    games: list,
    *,
    client=None,
    team_names_by_game_id: dict[int, tuple[str, str]] | None = None,
) -> list[GameProcessResult]:
    """Batch-fetch and persist boxscores for multiple NCAAB games via CBB API.

    Returns one GameProcessResult per game (same order as input).
    """
    from ..live.ncaab import NCAABLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..utils.date_utils import season_ending_year
    from ..utils.datetime_utils import now_utc, to_et_date

    if client is None:
        client = NCAABLiveFeedClient()

    results = [GameProcessResult() for _ in games]

    if not games:
        return results

    # Build team names lookup if not provided
    if team_names_by_game_id is None:
        from ..db import db_models
        team_names_by_game_id = {}
        for game in games:
            home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
            away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
            home_name = home_team.name if home_team else "Unknown"
            away_name = away_team.name if away_team else "Unknown"
            team_names_by_game_id[game.id] = (home_name, away_name)

    # Collect games with cbb_game_id
    cbb_game_ids = []
    cbb_team_names: dict[int, tuple[str, str]] = {}
    game_dates = []
    for game in games:
        ext = game.external_ids or {}
        cbb_game_id = ext.get("cbb_game_id")
        if not cbb_game_id:
            continue
        try:
            cbb_id = int(cbb_game_id)
            cbb_game_ids.append(cbb_id)
            cbb_team_names[cbb_id] = team_names_by_game_id.get(game.id, ("Unknown", "Unknown"))
            game_day = to_et_date(game.game_date)
            if game_day:
                game_dates.append(game_day)
        except (ValueError, TypeError):
            continue

    if not cbb_game_ids or not game_dates:
        return results

    start_date = min(game_dates)
    end_date = max(game_dates)
    season = season_ending_year(start_date)

    boxscores_by_id = client.fetch_boxscores_batch(
        cbb_game_ids, start_date, end_date, season, cbb_team_names,
    )
    # Batch endpoint counts as 2 API calls
    batch_api_calls = 2

    for i, game in enumerate(games):
        ext = game.external_ids or {}
        cbb_game_id = ext.get("cbb_game_id")
        if not cbb_game_id:
            continue
        try:
            cbb_id = int(cbb_game_id)
        except (ValueError, TypeError):
            continue

        results[i].api_calls = batch_api_calls  # share across batch
        boxscore = boxscores_by_id.get(cbb_id)
        if boxscore:
            if boxscore.team_boxscores:
                upsert_team_boxscores(
                    session, game.id, boxscore.team_boxscores,
                    source="cbb_api",
                )
            if boxscore.player_boxscores:
                upsert_player_boxscores(
                    session, game.id, boxscore.player_boxscores,
                    source="cbb_api",
                )
            game.last_boxscore_at = now_utc()
            results[i].boxscore_updated = True

    return results


# ---------------------------------------------------------------------------
# Dispatchers (route by league_code)
# ---------------------------------------------------------------------------


def process_game_pbp(session, game, league_code: str) -> GameProcessResult:
    """Dispatch PBP processing to the appropriate league handler."""
    if league_code == "NBA":
        return process_game_pbp_nba(session, game)
    elif league_code == "NHL":
        return process_game_pbp_nhl(session, game)
    elif league_code == "MLB":
        return process_game_pbp_mlb(session, game)
    elif league_code == "NCAAB":
        return process_game_pbp_ncaab(session, game)
    return GameProcessResult()


def process_game_boxscore(session, game, league_code: str) -> GameProcessResult:
    """Dispatch boxscore processing to the appropriate league handler."""
    if league_code == "NBA":
        return process_game_boxscore_nba(session, game)
    elif league_code == "NHL":
        return process_game_boxscore_nhl(session, game)
    elif league_code == "MLB":
        return process_game_boxscore_mlb(session, game)
    elif league_code == "NCAAB":
        return process_game_boxscore_ncaab(session, game)
    return GameProcessResult()
