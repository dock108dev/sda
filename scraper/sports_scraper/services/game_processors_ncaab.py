"""NCAAB per-game processing functions.

See game_processors.py for the shared GameProcessResult dataclass and
public dispatcher API.
"""

from __future__ import annotations

from ..logging import logger
from .game_processors import GameProcessResult


def process_game_pbp_ncaab(session, game, *, client=None) -> GameProcessResult:
    """Fetch and persist PBP for a single NCAAB game.

    Routing by game status:
    - scheduled/pregame: skip (nothing to fetch)
    - live: NCAA API only (real-time PBP)
    - final: CBB API first, NCAA API fallback
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

    # --- Scheduled/Pregame: nothing to fetch ---
    if game.status in (
        db_models.GameStatus.scheduled.value,
        db_models.GameStatus.pregame.value,
    ):
        return result

    # --- Live: NCAA API for real-time PBP ---
    if game.status == db_models.GameStatus.live.value:
        if ncaa_game_id:
            result = _fetch_ncaa_pbp(session, game, ncaa_game_id, client)
        return result

    # --- Final: CBB API first, NCAA API fallback ---
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
                return result

    # CBB had no data — try NCAA fallback for final games
    if ncaa_game_id and result.events_inserted == 0:
        ncaa_result = _fetch_ncaa_pbp(session, game, ncaa_game_id, client)
        result.api_calls += ncaa_result.api_calls
        result.events_inserted += ncaa_result.events_inserted
        if ncaa_result.transition:
            result.transition = ncaa_result.transition

    return result


def _fetch_ncaa_pbp(session, game, ncaa_game_id, client) -> GameProcessResult:
    """Fetch PBP from NCAA API for a single game."""
    from ..db import db_models
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    result = GameProcessResult()

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
