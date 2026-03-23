"""Play-by-play ingestion helpers.

Handles PBP fetching and persistence for different sources:
- NBA API (NBA)
- NHL API (NHL)
- College Basketball Data API (NCAAB)
- Sports Reference (NCAAB)

This module re-exports sport-specific functions from their dedicated modules.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from ..logging import logger
from ..persistence.plays import upsert_plays
from .game_selection import select_games_for_pbp_sportsref
from .mlb_boxscore_ingestion import populate_mlb_game_ids
from .pbp_mlb import (
    ingest_pbp_via_mlb_api,
    select_games_for_pbp_mlb_api,
)

# Re-export sport-specific functions
from .pbp_nba import (
    ingest_pbp_via_nba_api,
    populate_nba_game_ids,
    select_games_for_pbp_nba_api,
)
from .pbp_ncaab import (
    ingest_pbp_via_ncaab_api,
    select_games_for_pbp_ncaab_api,
)
from .pbp_nhl import (
    ingest_pbp_via_nhl_api,
    populate_nhl_game_ids,
    select_games_for_pbp_nhl_api,
)

__all__ = [
    # Main ingestion functions
    "ingest_pbp_via_sportsref",
    "ingest_pbp_via_nba_api",
    "ingest_pbp_via_nhl_api",
    "ingest_pbp_via_ncaab_api",
    "ingest_pbp_via_mlb_api",
    # Game selection functions
    "select_games_for_pbp_nba_api",
    "select_games_for_pbp_nhl_api",
    "select_games_for_pbp_ncaab_api",
    "select_games_for_pbp_mlb_api",
    # Game ID population functions
    "populate_nba_game_ids",
    "populate_nhl_game_ids",
    "populate_mlb_game_ids",
]


def ingest_pbp_via_sportsref(
    session: Session,
    *,
    run_id: int,
    league_code: str,
    scraper,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int]:
    """Ingest PBP using Sports Reference scraper implementations.

    Used for NCAAB. NBA and NHL use their respective live APIs
    (ingest_pbp_via_nba_api, ingest_pbp_via_nhl_api).
    """
    if not scraper:
        logger.info(
            "pbp_sportsref_not_supported",
            run_id=run_id,
            league=league_code,
            reason="no_sportsref_scraper",
        )
        return (0, 0)

    games = select_games_for_pbp_sportsref(
        session,
        league_code=league_code,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )
    logger.info(
        "pbp_sportsref_games_selected",
        run_id=run_id,
        league=league_code,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    pbp_games = 0
    pbp_events = 0
    for game_id, source_game_key, game_date in games:
        try:
            payload = scraper.fetch_play_by_play(source_game_key, game_date)
        except NotImplementedError:
            logger.warning(
                "pbp_unavailable_sportsref",
                run_id=run_id,
                league=league_code,
                reason="source_unavailable",
            )
            return (0, 0)
        except Exception as exc:
            logger.warning(
                "pbp_sportsref_fetch_failed",
                run_id=run_id,
                league=league_code,
                game_id=game_id,
                source_game_key=source_game_key,
                error=str(exc),
            )
            continue

        inserted = upsert_plays(session, game_id, payload.plays, source="sportsref")
        if inserted:
            pbp_games += 1
            pbp_events += inserted

    return (pbp_games, pbp_events)
