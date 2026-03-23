"""NBA historical data ingestion via Basketball Reference.

One-time backfill service for historical NBA seasons where the
NBA CDN API no longer serves data. Uses polite scraping (5-9s delays)
with local HTML caching so re-runs are instant for already-fetched pages.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores
from ..persistence.games import upsert_game
from ..persistence.plays import upsert_plays
from ..scrapers.nba_bref import NBABasketballReferenceScraper
from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc


def ingest_nba_historical_boxscores(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
    only_missing: bool = True,
) -> tuple[int, int, int]:
    """Backfill NBA boxscores from Basketball Reference.

    Iterates date-by-date, fetching scoreboard + boxscore pages.
    Per-game commit for crash resilience.

    Returns (games_processed, games_enriched, games_with_stats).
    """
    scraper = NBABasketballReferenceScraper()

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NBA"
    ).first()
    if not league:
        logger.warning("nba_historical_league_not_found")
        return (0, 0, 0)

    processed = 0
    enriched = 0
    with_stats = 0

    for day in scraper.iter_dates(start_date, end_date):
        try:
            games = scraper.fetch_games_for_date(day)
        except Exception as exc:
            logger.warning("nba_historical_date_failed", day=str(day), error=str(exc))
            continue

        for normalized_game in games:
            try:
                # Upsert game (creates stub if new, updates if existing)
                game_id, was_created = upsert_game(session, normalized_game)

                if only_missing and not was_created:
                    # Check if this game already has both team and player boxscores
                    has_team_box = session.query(db_models.SportsTeamBoxscore).filter(
                        db_models.SportsTeamBoxscore.game_id == game_id
                    ).first() is not None
                    has_player_box = session.query(db_models.SportsPlayerBoxscore).filter(
                        db_models.SportsPlayerBoxscore.game_id == game_id
                    ).first() is not None
                    if has_team_box and has_player_box:
                        continue

                # Upsert boxscores
                if normalized_game.team_boxscores:
                    upsert_team_boxscores(
                        session, game_id, normalized_game.team_boxscores,
                        source="basketball_reference",
                    )
                    enriched += 1

                if normalized_game.player_boxscores:
                    upsert_player_boxscores(
                        session, game_id, normalized_game.player_boxscores,
                        source="basketball_reference",
                    )
                    with_stats += 1

                session.commit()
                processed += 1

                logger.info(
                    "nba_historical_game_ingested",
                    game_id=game_id,
                    game_key=normalized_game.identity.source_game_key,
                    created=was_created,
                )

            except Exception as exc:
                session.rollback()
                logger.warning(
                    "nba_historical_game_failed",
                    game_key=normalized_game.identity.source_game_key,
                    error=str(exc),
                )
                continue

    logger.info(
        "nba_historical_boxscores_complete",
        run_id=run_id,
        start=str(start_date),
        end=str(end_date),
        processed=processed,
        enriched=enriched,
        with_stats=with_stats,
    )
    return (processed, enriched, with_stats)


def ingest_nba_historical_pbp(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
    only_missing: bool = True,
) -> int:
    """Backfill NBA play-by-play from Basketball Reference.

    Selects games in the date range that have a source_game_key
    (set during boxscore ingestion) and fetches PBP for each.

    Returns count of games processed.
    """
    scraper = NBABasketballReferenceScraper()

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NBA"
    ).first()
    if not league:
        return 0

    # Find games in date range with a source_game_key
    window_start = start_of_et_day_utc(start_date)
    window_end = end_of_et_day_utc(end_date)

    games = (
        session.query(
            db_models.SportsGame.id,
            db_models.SportsGame.source_game_key,
            db_models.SportsGame.game_date,
        )
        .filter(
            db_models.SportsGame.league_id == league.id,
            db_models.SportsGame.game_date >= window_start,
            db_models.SportsGame.game_date < window_end,
            db_models.SportsGame.source_game_key.isnot(None),
        )
        .all()
    )

    if not games:
        logger.info("nba_historical_pbp_no_games", run_id=run_id)
        return 0

    processed = 0
    for game_id, source_game_key, game_date in games:
        if only_missing:
            has_plays = session.query(db_models.SportsGamePlay).filter(
                db_models.SportsGamePlay.game_id == game_id
            ).first() is not None
            if has_plays:
                continue

        try:
            pbp = scraper.fetch_play_by_play(source_game_key, game_date.date() if game_date else start_date)
            if pbp.plays:
                upsert_plays(
                    session, game_id, pbp.plays,
                    source="basketball_reference",
                )
                session.commit()
                processed += 1
                logger.info(
                    "nba_historical_pbp_ingested",
                    game_id=game_id,
                    game_key=source_game_key,
                    plays=len(pbp.plays),
                )
        except NotImplementedError:
            continue
        except Exception as exc:
            session.rollback()
            logger.warning(
                "nba_historical_pbp_failed",
                game_id=game_id,
                game_key=source_game_key,
                error=str(exc),
            )
            continue

    logger.info(
        "nba_historical_pbp_complete",
        run_id=run_id,
        processed=processed,
        total_candidates=len(games),
    )
    return processed
