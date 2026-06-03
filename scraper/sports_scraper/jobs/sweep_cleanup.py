"""Daily sweep cleanup helper phases."""

from __future__ import annotations

from datetime import timedelta

from ..db import get_session
from ..logging import logger


def _archive_old_games() -> dict:
    """Archive final games >7 days with complete artifacts.

    This is the same operation as game_state_updater._promote_final_to_archived
    but runs as part of the daily sweep for completeness.
    """
    from ..services.game_state_updater import _promote_final_to_archived

    with get_session() as session:
        archived = _promote_final_to_archived(session)

    return {"archived": archived}


def _prune_old_job_runs(retention_days: int = 7) -> dict:
    """Delete job run records older than retention_days.

    At ~900 rows/day (all recurring tasks), 7-day retention keeps
    the table at ~6300 rows max — trivial for Postgres.
    """
    from ..db import db_models
    from ..utils.datetime_utils import now_utc

    cutoff = now_utc() - timedelta(days=retention_days)

    with get_session() as session:
        deleted = (
            session.query(db_models.SportsJobRun)
            .filter(db_models.SportsJobRun.created_at < cutoff)
            .delete(synchronize_session="fetch")
        )

    logger.info(
        "job_runs_pruned",
        deleted=deleted,
        retention_days=retention_days,
    )

    return {"deleted": deleted, "retention_days": retention_days}


def _purge_completed_game_odds() -> dict:
    """Delete fairbet_game_odds_work rows for final/archived games.

    The work table is meant to hold only active pregame odds. Once a game
    completes, its odds rows are never cleaned up by the per-batch stale
    DELETE (which only fires when new odds are upserted). Without this
    cleanup the table grows unbounded — 1.5M+ rows causing 30+ second
    query times from IO contention.
    """
    from sqlalchemy import text

    with get_session() as session:
        result = session.execute(text("""
            DELETE FROM fairbet_game_odds_work
            WHERE game_id IN (
                SELECT id FROM sports_games
                WHERE status IN ('final', 'archived')
            )
        """))
        deleted = result.rowcount
        session.commit()

    if deleted:
        logger.info("fairbet_odds_purge_complete", deleted=deleted)
    else:
        logger.debug("fairbet_odds_purge_nothing_to_delete")

    return {"deleted": deleted}


def _purge_test_users() -> dict:
    """Delete Playwright/CI test users created by e2e test runs.

    Matches two patterns:
    - ``e2e-*@test.scrolldown.dev`` (Playwright e2e tests)
    - ``test+*@example.com``       (CI signup tests)
    """
    from sqlalchemy import text

    with get_session() as session:
        result = session.execute(text("""
            DELETE FROM users
            WHERE email LIKE 'e2e-%@test.scrolldown.dev'
               OR email LIKE 'test+%@example.com'
        """))
        deleted = result.rowcount
        session.commit()

    if deleted:
        logger.info("test_user_purge_complete", deleted=deleted)
    else:
        logger.debug("test_user_purge_nothing_to_delete")

    return {"deleted": deleted}
