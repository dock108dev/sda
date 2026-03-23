"""NCAAB batch polling helpers.

Data source strategy (SSOT):
- CBB API (api.collegebasketballdata.com) is the single source of truth for
  PBP and boxscores. All games use cbb_game_id for data fetching.
- NCAA API scoreboard (ncaa-api.henrygd.me) is used only for real-time status
  transitions and score updates (1 API call for all games). It also stores
  ncaa_game_id for reference but this does NOT affect PBP/boxscore routing.

Called by poll_live_pbp_task in polling_tasks.py.

Per-game processing logic lives in services.game_processors (SSOT).
"""

from __future__ import annotations

import random
import time

from ..logging import logger
from ..utils.datetime_utils import to_et_date
from .polling_helpers import _JITTER_MAX, _JITTER_MIN, _RateLimitError


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

    game_dates = [to_et_date(g.game_date) for g in games if g.game_date]
    if not game_dates:
        return transitions

    start_date = min(game_dates)
    end_date = max(game_dates)

    try:
        cbb_games = client.fetch_games(start_date, end_date)
    except Exception as exc:
        logger.warning("ncaab_status_fetch_error", error=str(exc))
        return transitions

    # Build cbb_game_id -> status and score maps
    cbb_status_map: dict[int, str] = {}
    cbb_score_map: dict[int, tuple[int | None, int | None]] = {}
    for cg in cbb_games:
        cbb_status_map[cg.game_id] = cg.status
        cbb_score_map[cg.game_id] = (cg.home_score, cg.away_score)

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

        # Update scores from CBB API (mirrors NCAA API score update path)
        scores = cbb_score_map.get(cbb_id)
        if scores:
            home_score, away_score = scores
            if home_score is not None:
                game.home_score = home_score
            if away_score is not None:
                game.away_score = away_score

    return transitions


def _poll_ncaab_games_batch(session, games: list) -> dict:
    """Poll PBP and boxscores for NCAAB games.

    Uses CBB API (cbb_game_id) as primary source, with NCAA API
    (ncaa_game_id) as fallback for PBP and boxscores when CBB data
    is unavailable or the game lacks a cbb_game_id.

    Per-game processing delegates to game_processors (SSOT).
    Batch boxscores use game_processors.process_game_boxscores_ncaab_batch.
    """
    from ..db import db_models
    from ..live.ncaab import NCAABLiveFeedClient
    from ..services.game_processors import (
        process_game_boxscore_ncaab,
        process_game_boxscores_ncaab_batch,
        process_game_pbp_ncaab,
    )

    client = NCAABLiveFeedClient()

    # Status transitions (NCAA scoreboard + CBB API fallback)
    ncaab_transitions = _update_ncaab_statuses(session, games, client)
    api_calls = 1 if games else 0  # count the scoreboard call
    pbp_updated = 0
    boxscores_updated = 0

    # Collect eligible games
    eligible_games: list = []
    team_names_by_game_id: dict[int, tuple[str, str]] = {}

    for game in games:
        home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
        away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
        home_name = home_team.name if home_team else "Unknown"
        away_name = away_team.name if away_team else "Unknown"
        team_names_by_game_id[game.id] = (home_name, away_name)

        ext = game.external_ids or {}
        cbb_game_id = ext.get("cbb_game_id")
        ncaa_game_id = ext.get("ncaa_game_id")
        if cbb_game_id or ncaa_game_id:
            eligible_games.append(game)
        else:
            logger.info(
                "poll_ncaab_skip_no_game_id",
                game_id=game.id,
                status=game.status,
            )

    if not eligible_games:
        return {"api_calls": api_calls, "pbp_updated": 0, "boxscores_updated": 0}

    logger.info(
        "poll_ncaab_batch_start",
        eligible_games=len(eligible_games),
        total_games=len(games),
    )

    # --- PBP: per-game via game_processors ---
    for game in eligible_games:
        if api_calls > 0:
            time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

        try:
            pbp_result = process_game_pbp_ncaab(session, game, client=client)
            api_calls += pbp_result.api_calls
            if pbp_result.events_inserted:
                pbp_updated += 1
            if pbp_result.transition:
                ncaab_transitions.append(pbp_result.transition)
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning(
                "poll_ncaab_pbp_error",
                game_id=game.id,
                error=str(exc),
            )

    # --- Boxscores Phase 1: CBB API batch for live/final games ---
    live_or_final = [
        g for g in eligible_games
        if g.status in (db_models.GameStatus.live.value, db_models.GameStatus.final.value)
    ]

    cbb_live_or_final = [
        g for g in live_or_final if (g.external_ids or {}).get("cbb_game_id")
    ]

    games_with_boxscore: set[int] = set()

    if cbb_live_or_final:
        if api_calls > 0:
            time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

        try:
            batch_results = process_game_boxscores_ncaab_batch(
                session,
                cbb_live_or_final,
                client=client,
                team_names_by_game_id=team_names_by_game_id,
            )
            for game, br in zip(cbb_live_or_final, batch_results, strict=False):
                if br.boxscore_updated:
                    boxscores_updated += 1
                    games_with_boxscore.add(game.id)
            # batch counts as 2 API calls
            api_calls += 2
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning(
                "poll_ncaab_cbb_boxscore_batch_error",
                game_count=len(cbb_live_or_final),
                error=str(exc),
            )

    # --- Boxscores Phase 2: NCAA API fallback (per-game for missing boxscores) ---
    ncaa_box_candidates = [
        g for g in live_or_final
        if g.id not in games_with_boxscore and (g.external_ids or {}).get("ncaa_game_id")
    ]

    for game in ncaa_box_candidates:
        if api_calls > 0:
            time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

        try:
            box_result = process_game_boxscore_ncaab(session, game, client=client)
            api_calls += box_result.api_calls
            if box_result.boxscore_updated:
                boxscores_updated += 1
                games_with_boxscore.add(game.id)
        except Exception as exc:
            if "429" in str(exc):
                raise _RateLimitError() from exc
            logger.warning(
                "poll_ncaab_ncaa_boxscore_error",
                game_id=game.id,
                ncaa_game_id=(game.external_ids or {}).get("ncaa_game_id"),
                error=str(exc),
            )

    logger.info(
        "poll_ncaab_batch_complete",
        api_calls=api_calls,
        pbp_updated=pbp_updated,
        boxscores_updated=boxscores_updated,
        eligible_games=len(eligible_games),
    )

    return {
        "api_calls": api_calls,
        "pbp_updated": pbp_updated,
        "boxscores_updated": boxscores_updated,
        "transitions": ncaab_transitions,
    }
