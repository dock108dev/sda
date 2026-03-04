"""NCAAB batch polling helpers.

NCAAB live data flows through two APIs based on which external ID is available:

1. NCAA API (ncaa-api.henrygd.me) — uses ncaa_game_id, obtained via scoreboard
   matching. Provides PBP, boxscores, and real-time status/scores.
2. CBB API (api.collegebasketballdata.com) — uses cbb_game_id, populated in
   Phase 0 of the polling task. Provides PBP, boxscores, and status.

Both are first-class data paths. A game routes through whichever API has a
matching ID. Games with ncaa_game_id use the NCAA API; games with only
cbb_game_id use the CBB API. Status updates always attempt both sources
so that games without a scoreboard match still transition correctly.

Called by poll_live_pbp_task in polling_tasks.py.
"""

from __future__ import annotations

import random
import time

from ..logging import logger
from .polling_helpers import _JITTER_MIN, _JITTER_MAX, _RateLimitError


def _match_ncaa_scoreboard_to_games(
    session, games: list, scoreboard_games: list,
) -> dict:
    """Match NCAA scoreboard entries to DB games by team name normalization.

    For each DB game, tries to find a matching NCAA scoreboard game by
    normalizing both home and away team names and comparing.

    Returns dict mapping DB game.id -> NCAAScoreboardGame.
    """
    from ..db import db_models
    from ..normalization import normalize_team_name

    # Build lookup: (home_canonical, away_canonical) -> scoreboard game
    scoreboard_by_teams: dict[tuple[str, str], object] = {}
    for sg in scoreboard_games:
        home_canonical, _ = normalize_team_name("NCAAB", sg.home_team_short)
        away_canonical, _ = normalize_team_name("NCAAB", sg.away_team_short)
        scoreboard_by_teams[(home_canonical, away_canonical)] = sg

    matches: dict = {}
    for game in games:
        # Skip if already has ncaa_game_id
        if (game.external_ids or {}).get("ncaa_game_id"):
            continue

        home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
        away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
        if not home_team or not away_team:
            continue

        home_canonical, _ = normalize_team_name("NCAAB", home_team.name)
        away_canonical, _ = normalize_team_name("NCAAB", away_team.name)

        # Try normal match
        sg = scoreboard_by_teams.get((home_canonical, away_canonical))

        # Try reversed (neutral site games may swap home/away)
        if sg is None:
            sg = scoreboard_by_teams.get((away_canonical, home_canonical))

        if sg is not None:
            matches[game.id] = sg

    return matches


def _update_ncaab_statuses(session, games: list, client) -> list[dict]:
    """Check both NCAA and CBB APIs for game statuses and apply transitions.

    Phase 1: NCAA API scoreboard (1 API call for all games).
        - Matches games to ncaa_game_id via team name normalization.
        - Updates status and scores for matched games.

    Phase 2: CBB API schedule (1 API call for the date range).
        - Covers games that the NCAA scoreboard didn't match.
        - When the NCAA scoreboard fails entirely, covers all games.

    Also stores ncaa_game_id in external_ids for newly matched games.

    Returns list of transition dicts for logging.
    """
    from ..db import db_models
    from ..persistence.games import resolve_status_transition
    from ..utils.datetime_utils import now_utc

    transitions: list[dict] = []
    now = now_utc()

    # --- Phase 1: NCAA API scoreboard ---
    ncaa_success = False
    try:
        scoreboard_games = client.fetch_ncaa_scoreboard()
        if scoreboard_games:
            ncaa_success = True
            logger.info(
                "ncaab_status_using_ncaa_scoreboard",
                scoreboard_count=len(scoreboard_games),
                db_games=len(games),
            )

            # Match scoreboard games to DB games
            matches = _match_ncaa_scoreboard_to_games(session, games, scoreboard_games)

            # Build ncaa_game_id -> status map for all scoreboard games
            ncaa_id_status: dict[str, str] = {
                sg.ncaa_game_id: sg.game_state for sg in scoreboard_games
            }
            ncaa_id_scores: dict[str, tuple] = {
                sg.ncaa_game_id: (sg.home_score, sg.away_score) for sg in scoreboard_games
            }

            for game in games:
                # Store ncaa_game_id for newly matched games
                if game.id in matches:
                    sg = matches[game.id]
                    ext = dict(game.external_ids or {})
                    ext["ncaa_game_id"] = sg.ncaa_game_id
                    game.external_ids = ext
                    logger.info(
                        "ncaab_ncaa_game_id_stored",
                        game_id=game.id,
                        ncaa_game_id=sg.ncaa_game_id,
                    )

                ncaa_game_id = (game.external_ids or {}).get("ncaa_game_id")
                if not ncaa_game_id:
                    continue

                api_status = ncaa_id_status.get(ncaa_game_id)
                if not api_status:
                    continue

                new_status = resolve_status_transition(game.status, api_status)
                if new_status != game.status:
                    old_status = game.status
                    game.status = new_status
                    game.updated_at = now

                    if new_status == db_models.GameStatus.final.value and game.end_time is None:
                        game.end_time = now

                    transitions.append({
                        "game_id": game.id,
                        "from": old_status,
                        "to": new_status,
                    })
                    logger.info(
                        "poll_ncaab_status_transition",
                        game_id=game.id,
                        from_status=old_status,
                        to_status=new_status,
                        ncaa_game_id=ncaa_game_id,
                        source="ncaa_api",
                    )

                # Update scores from scoreboard
                scores = ncaa_id_scores.get(ncaa_game_id)
                if scores:
                    home_score, away_score = scores
                    if home_score is not None:
                        game.home_score = home_score
                    if away_score is not None:
                        game.away_score = away_score

    except Exception as exc:
        logger.warning("ncaa_scoreboard_error", error=str(exc))

    # --- Phase 2: CBB API status for games without ncaa_game_id ---
    # Some games never appear on the NCAA scoreboard (name mismatch, lower
    # divisions, etc.). The CBB API uses cbb_game_id which is populated
    # reliably in Phase 0, so we always check it for unmatched games.
    # When the NCAA scoreboard fails entirely, this covers all games.
    cbb_status_games = [
        g for g in games
        if not (g.external_ids or {}).get("ncaa_game_id")
        and (g.external_ids or {}).get("cbb_game_id")
    ]

    if not ncaa_success:
        logger.info("ncaab_status_ncaa_unavailable_using_cbb")
        cbb_status_games = [
            g for g in games if (g.external_ids or {}).get("cbb_game_id")
        ]

    if not cbb_status_games:
        return transitions

    logger.info(
        "ncaab_status_cbb_update",
        games_count=len(cbb_status_games),
        ncaa_available=ncaa_success,
    )

    game_dates = [g.game_date.date() for g in games if g.game_date]
    if not game_dates:
        return transitions

    start_date = min(game_dates)
    end_date = max(game_dates)

    try:
        cbb_games = client.fetch_games(start_date, end_date)
    except Exception as exc:
        logger.warning("ncaab_status_fetch_error", error=str(exc))
        return transitions

    # Build cbb_game_id -> status map
    cbb_status_map: dict[int, str] = {}
    for cg in cbb_games:
        cbb_status_map[cg.game_id] = cg.status

    for game in cbb_status_games:
        cbb_game_id = (game.external_ids or {}).get("cbb_game_id")
        if not cbb_game_id:
            continue

        try:
            cbb_id = int(cbb_game_id)
        except (ValueError, TypeError):
            continue

        api_status = cbb_status_map.get(cbb_id)
        if not api_status:
            continue

        new_status = resolve_status_transition(game.status, api_status)
        if new_status != game.status:
            old_status = game.status
            game.status = new_status
            game.updated_at = now

            if new_status == db_models.GameStatus.final.value and game.end_time is None:
                game.end_time = now

            transitions.append({
                "game_id": game.id,
                "from": old_status,
                "to": new_status,
            })
            logger.info(
                "poll_ncaab_status_transition",
                game_id=game.id,
                from_status=old_status,
                to_status=new_status,
                cbb_game_id=cbb_id,
                source="cbb_api",
            )

    return transitions


def _poll_ncaab_games_batch(session, games: list) -> dict:
    """Poll PBP and boxscores for NCAAB games in batch.

    Routes each game to the appropriate API based on available external IDs:
    - NCAA API for games with ncaa_game_id
    - CBB API for games with only cbb_game_id
    """
    from ..db import db_models
    from ..live.ncaab import NCAABLiveFeedClient
    from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
    from ..persistence.plays import upsert_plays
    from ..utils.datetime_utils import now_utc

    client = NCAABLiveFeedClient()

    # Status transitions (NCAA scoreboard + CBB API for unmatched games)
    ncaab_transitions = _update_ncaab_statuses(session, games, client)
    api_calls = 1 if games else 0  # count the scoreboard call
    pbp_updated = 0
    boxscores_updated = 0

    # Partition games by data source
    ncaa_games: list = []
    cbb_games: list = []
    team_names_by_game_id: dict[int, tuple[str, str]] = {}  # DB game.id -> (home, away)
    team_abbrs_by_game_id: dict[int, tuple[str, str]] = {}  # DB game.id -> (home_abbr, away_abbr)

    for game in games:
        # Resolve team names and abbreviations (needed for PBP and boxscores)
        home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
        away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
        home_name = home_team.name if home_team else "Unknown"
        away_name = away_team.name if away_team else "Unknown"
        team_names_by_game_id[game.id] = (home_name, away_name)
        team_abbrs_by_game_id[game.id] = (
            home_team.abbreviation if home_team and home_team.abbreviation else home_name,
            away_team.abbreviation if away_team and away_team.abbreviation else away_name,
        )

        ncaa_game_id = (game.external_ids or {}).get("ncaa_game_id")
        cbb_game_id = (game.external_ids or {}).get("cbb_game_id")

        if ncaa_game_id:
            ncaa_games.append(game)
        elif cbb_game_id:
            cbb_games.append(game)
        else:
            logger.info(
                "poll_ncaab_skip_no_game_id",
                game_id=game.id,
                status=game.status,
            )

    if not ncaa_games and not cbb_games:
        return {"api_calls": api_calls, "pbp_updated": 0, "boxscores_updated": 0}

    logger.info(
        "poll_ncaab_batch_start",
        ncaa_games=len(ncaa_games),
        cbb_games=len(cbb_games),
        total_games=len(games),
    )

    # --- PBP: NCAA API ---
    for game in ncaa_games:
        ncaa_game_id = game.external_ids["ncaa_game_id"]
        home_abbr, away_abbr = team_abbrs_by_game_id[game.id]

        if api_calls > 0:
            time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

        try:
            payload = client.fetch_ncaa_play_by_play(
                ncaa_game_id,
                game_status=game.status,
                home_abbr=home_abbr,
                away_abbr=away_abbr,
            )
            api_calls += 1

            if payload.plays:
                inserted = upsert_plays(session, game.id, payload.plays, source="ncaa_api")
                if inserted:
                    pbp_updated += 1
                game.last_pbp_at = now_utc()

                if game.status == db_models.GameStatus.pregame.value:
                    game.status = db_models.GameStatus.live.value
                    game.updated_at = now_utc()
                    ncaab_transitions.append({
                        "game_id": game.id,
                        "from": "pregame",
                        "to": "live",
                    })
                    logger.info(
                        "poll_pbp_inferred_live",
                        game_id=game.id,
                        league="NCAAB",
                        reason="pbp_plays_found",
                        play_count=len(payload.plays),
                        ncaa_game_id=ncaa_game_id,
                    )

        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning(
                "poll_ncaab_pbp_error",
                game_id=game.id,
                ncaa_game_id=ncaa_game_id,
                source="ncaa_api",
                error=str(exc),
            )

    # --- PBP: CBB API ---
    for game in cbb_games:
        cbb_game_id = game.external_ids["cbb_game_id"]

        if api_calls > 0:
            time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

        try:
            cbb_id = int(cbb_game_id)
        except (ValueError, TypeError):
            logger.warning(
                "poll_ncaab_cbb_invalid_id",
                game_id=game.id,
                cbb_game_id=cbb_game_id,
            )
            continue

        try:
            payload = client.fetch_play_by_play(cbb_id, game_status=game.status)
            api_calls += 1

            if payload.plays:
                inserted = upsert_plays(session, game.id, payload.plays, source="cbb_api")
                if inserted:
                    pbp_updated += 1
                game.last_pbp_at = now_utc()

                if game.status == db_models.GameStatus.pregame.value:
                    game.status = db_models.GameStatus.live.value
                    game.updated_at = now_utc()
                    ncaab_transitions.append({
                        "game_id": game.id,
                        "from": "pregame",
                        "to": "live",
                    })
                    logger.info(
                        "poll_pbp_inferred_live",
                        game_id=game.id,
                        league="NCAAB",
                        reason="pbp_plays_found",
                        play_count=len(payload.plays),
                        cbb_game_id=cbb_id,
                    )
            else:
                logger.debug(
                    "poll_ncaab_cbb_no_plays",
                    game_id=game.id,
                    cbb_game_id=cbb_id,
                )

        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning(
                "poll_ncaab_pbp_error",
                game_id=game.id,
                cbb_game_id=cbb_id,
                source="cbb_api",
                error=str(exc),
            )

    # --- Boxscores: NCAA API (per-game for live/final games) ---
    ncaa_live_or_final = [
        g for g in ncaa_games
        if g.status in (db_models.GameStatus.live.value, db_models.GameStatus.final.value)
    ]

    for game in ncaa_live_or_final:
        ncaa_game_id = game.external_ids["ncaa_game_id"]
        home_name, away_name = team_names_by_game_id[game.id]

        if api_calls > 0:
            time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

        try:
            boxscore = client.fetch_ncaa_boxscore(
                ncaa_game_id, home_name, away_name, game_status=game.status,
            )
            api_calls += 1

            if boxscore:
                if boxscore.team_boxscores:
                    upsert_team_boxscores(
                        session, game.id, boxscore.team_boxscores, source="ncaa_api",
                    )
                if boxscore.player_boxscores:
                    upsert_player_boxscores(
                        session, game.id, boxscore.player_boxscores, source="ncaa_api",
                    )
                game.last_boxscore_at = now_utc()
                boxscores_updated += 1

        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning(
                "poll_ncaab_boxscore_error",
                game_id=game.id,
                ncaa_game_id=ncaa_game_id,
                error=str(exc),
            )

    # --- Boxscores: CBB API (batch for live/final games) ---
    cbb_live_or_final = [
        g for g in cbb_games
        if g.status in (db_models.GameStatus.live.value, db_models.GameStatus.final.value)
    ]

    if cbb_live_or_final:
        game_dates = [g.game_date.date() for g in cbb_live_or_final if g.game_date]
        if game_dates:
            start_date = min(game_dates)
            end_date = max(game_dates)

            cbb_game_ids = []
            cbb_team_names: dict[int, tuple[str, str]] = {}
            for game in cbb_live_or_final:
                try:
                    cbb_id = int(game.external_ids["cbb_game_id"])
                    cbb_game_ids.append(cbb_id)
                    cbb_team_names[cbb_id] = team_names_by_game_id[game.id]
                except (ValueError, TypeError):
                    continue

            if cbb_game_ids:
                if api_calls > 0:
                    time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

                try:
                    from ..utils.date_utils import season_ending_year

                    season = season_ending_year(start_date)
                    boxscores_by_id = client.fetch_boxscores_batch(
                        cbb_game_ids, start_date, end_date, season, cbb_team_names,
                    )
                    api_calls += 2  # batch endpoint typically makes 2 API calls

                    for game in cbb_live_or_final:
                        try:
                            cbb_id = int(game.external_ids["cbb_game_id"])
                        except (ValueError, TypeError):
                            continue

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
                            boxscores_updated += 1

                except Exception as exc:
                    if "429" in str(exc):
                        raise _RateLimitError() from exc
                    logger.warning(
                        "poll_ncaab_cbb_boxscore_batch_error",
                        game_count=len(cbb_game_ids),
                        error=str(exc),
                    )

    logger.info(
        "poll_ncaab_batch_complete",
        api_calls=api_calls,
        pbp_updated=pbp_updated,
        boxscores_updated=boxscores_updated,
        ncaa_games=len(ncaa_games),
        cbb_games=len(cbb_games),
    )

    return {
        "api_calls": api_calls,
        "pbp_updated": pbp_updated,
        "boxscores_updated": boxscores_updated,
        "transitions": ncaab_transitions,
    }
