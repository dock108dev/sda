"""Celery task for bulk game flow generation.

This task runs in the api-worker container and processes bulk game flow
generation requests asynchronously. Job state is persisted in the
database for consistency and survives worker restarts.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from ..celery_app import celery_app
from ..config import settings
from ..db.flow import SportsGameFlow
from ..db.mlb_advanced import (  # noqa: F401 — register model for relationship resolution
    MLBGameAdvancedStats,
    MLBPlayerAdvancedStats,
)
from ..db.nba_advanced import NBAGameAdvancedStats, NBAPlayerAdvancedStats  # noqa: F401
from ..db.ncaab_advanced import NCAABGameAdvancedStats, NCAABPlayerAdvancedStats  # noqa: F401
from ..db.nfl_advanced import NFLGameAdvancedStats, NFLPlayerAdvancedStats  # noqa: F401
from ..db.nhl_advanced import (  # noqa: F401
    NHLGameAdvancedStats,
    NHLGoalieAdvancedStats,
    NHLSkaterAdvancedStats,
)
from ..db.odds import SportsGameOdds  # noqa: F401 — register model for relationship resolution
from ..db.pipeline import BulkFlowGenerationJob
from ..db.scraper import SportsScrapeRun  # noqa: F401 — register model for relationship resolution
from ..db.social import TeamSocialPost  # noqa: F401 — register model for relationship resolution
from ..db.sports import SportsGame, SportsGamePlay, SportsLeague
from ..services.pipeline import PipelineExecutor

logger = logging.getLogger(__name__)

# Hard ceiling on the number of games a single bulk job may process. The job
# record's ``max_games`` is supplied by an admin caller; a typo or compromised
# admin key could otherwise queue a multi-year window with no bound, tying a
# Celery worker for hours. Bounded here as a defense-in-depth backstop.
_BULK_JOB_HARD_GAME_CAP = 2000

# Cap stored per-game failure strings so unexpected exceptions (e.g. SQL state
# strings, raw provider responses) cannot bloat ``errors_json`` indefinitely
# nor smuggle large payloads into the admin UI.
_FAILURE_REASON_MAX_CHARS = 500


def _truncate_failure_reason(reason: str) -> str:
    if len(reason) <= _FAILURE_REASON_MAX_CHARS:
        return reason
    return reason[: _FAILURE_REASON_MAX_CHARS - 1] + "…"


async def _count_pbp_and_goals(
    session: AsyncSession, game_id: int
) -> tuple[int, int]:
    """Return (play_count, scoring_play_count) for a game.

    A scoring play is any play where ``home_score`` or ``away_score``
    differs from the prior play (or is non-zero on the first play). This
    matches ``score_detection.is_scoring_play`` and is league-agnostic, so
    it correctly counts NHL goals as scoring plays.
    """
    result = await session.execute(
        select(SportsGamePlay.home_score, SportsGamePlay.away_score)
        .where(SportsGamePlay.game_id == game_id)
        .order_by(SportsGamePlay.play_index)
    )
    rows = list(result.all())
    if not rows:
        return 0, 0

    scoring = 0
    prev_home: int | None = None
    prev_away: int | None = None
    for home, away in rows:
        h = home or 0
        a = away or 0
        if prev_home is None:
            if h > 0 or a > 0:
                scoring += 1
        elif h != prev_home or a != prev_away:
            scoring += 1
        prev_home = h
        prev_away = a

    return len(rows), scoring


async def _run_bulk_generation_async(job_id: int) -> None:
    """Async implementation of bulk game flow generation.

    Creates a fresh async engine bound to the current event loop to avoid
    the "Future attached to a different loop" error that occurs when reusing
    an engine created in a different context (e.g., module import time).

    Args:
        job_id: Database ID of the BulkFlowGenerationJob record
    """
    # Create fresh engine bound to this event loop
    engine = create_async_engine(settings.database_url, echo=False, future=True)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    try:
        async with session_factory() as session:
            # Load the job record
            job_result = await session.execute(
                select(BulkFlowGenerationJob).where(
                    BulkFlowGenerationJob.id == job_id
                )
            )
            job = job_result.scalar_one_or_none()
            if not job:
                logger.error(f"Bulk job {job_id} not found")
                return

            # Mark job as running
            job.status = "running"
            job.started_at = datetime.utcnow()
            await session.commit()

            logger.info(f"Starting bulk flow generation job {job_id}")

            try:
                # Query games in the date range for specified leagues
                query = (
                    select(SportsGame)
                    .join(SportsLeague)
                    .options(
                        selectinload(SportsGame.home_team),
                        selectinload(SportsGame.away_team),
                    )
                    .where(
                        and_(
                            SportsGame.game_date >= job.start_date,
                            SportsGame.game_date <= job.end_date,
                            SportsGame.status == "final",
                        )
                    )
                    .order_by(SportsGame.game_date)
                )

                # Filter by leagues if specified
                if job.leagues:
                    query = query.where(SportsLeague.code.in_(job.leagues))

                # Exclude games that already have flows (unless force regenerate)
                if not job.force_regenerate:
                    existing_flow_game_ids = (
                        select(SportsGameFlow.game_id).where(
                            SportsGameFlow.moments_json.isnot(None)
                        )
                    )
                    query = query.where(
                        SportsGame.id.notin_(existing_flow_game_ids)
                    )

                # Eager-load league so per-game logs can include the league
                # code (especially important for NHL diagnostics).
                query = query.options(selectinload(SportsGame.league))
                result = await session.execute(query)
                games = list(result.scalars().all())

                # Apply max_games limit before per-game work so caps are
                # respected even when many games would otherwise be skipped.
                # Always enforce the hard ceiling: a missing/oversized
                # ``max_games`` must not produce an unbounded job.
                requested_cap = (
                    job.max_games
                    if (job.max_games is not None and job.max_games > 0)
                    else _BULK_JOB_HARD_GAME_CAP
                )
                effective_cap = min(requested_cap, _BULK_JOB_HARD_GAME_CAP)
                if effective_cap < requested_cap:
                    logger.warning(
                        "bulk_flow_max_games_clamped",
                        extra={
                            "job_id": job_id,
                            "requested": requested_cap,
                            "effective": effective_cap,
                            "hard_cap": _BULK_JOB_HARD_GAME_CAP,
                        },
                    )
                if len(games) > effective_cap:
                    games = games[:effective_cap]
                    logger.info(
                        f"Job {job_id}: Limited to {effective_cap} games "
                        f"(requested={requested_cap}, hard_cap={_BULK_JOB_HARD_GAME_CAP})"
                    )

                job.total_games = len(games)
                await session.commit()

                logger.info(f"Job {job_id}: Found {len(games)} candidate games")

                errors_list: list[dict[str, Any]] = []

                for i, game in enumerate(games):
                    job.current_game = i + 1
                    await session.commit()

                    league_code = game.league.code if game.league else None
                    pbp_count, goals_found = await _count_pbp_and_goals(
                        session, game.id
                    )
                    pbp_exists = pbp_count > 0

                    # Skip games without PBP — log explicit reason instead of
                    # silently dropping. This matters for NHL where missing
                    # PBP is the most common cause of empty flows.
                    if not pbp_exists:
                        job.skipped += 1
                        await session.commit()
                        logger.info(
                            "bulk_flow_skip",
                            extra={
                                "job_id": job_id,
                                "game_id": game.id,
                                "league": league_code,
                                "pbp_exists": False,
                                "goals_found": 0,
                                "flow_attempted": False,
                                "skip_reason": "no_pbp_data",
                            },
                        )
                        await asyncio.sleep(0.2)
                        continue

                    # Skip games with PBP but zero scoring plays — a flow with
                    # no scoring events cannot satisfy the minimum NHL flow
                    # contract (final score, goals by period, scoring team).
                    if goals_found == 0:
                        job.skipped += 1
                        await session.commit()
                        logger.info(
                            "bulk_flow_skip",
                            extra={
                                "job_id": job_id,
                                "game_id": game.id,
                                "league": league_code,
                                "pbp_exists": True,
                                "goals_found": 0,
                                "flow_attempted": False,
                                "skip_reason": "no_scoring_plays",
                            },
                        )
                        await asyncio.sleep(0.2)
                        continue

                    # Run the full pipeline
                    try:
                        executor = PipelineExecutor(session)
                        await executor.run_full_pipeline(
                            game_id=game.id,
                            triggered_by="bulk_celery",
                        )
                        await session.commit()
                        job.successful += 1
                        await session.commit()
                        logger.info(
                            "bulk_flow_success",
                            extra={
                                "job_id": job_id,
                                "game_id": game.id,
                                "league": league_code,
                                "pbp_exists": True,
                                "goals_found": goals_found,
                                "flow_attempted": True,
                                "failure_reason": None,
                            },
                        )
                    # Per-game broad catch: a single bad game must NOT kill
                    # the bulk job. Failure is fully recorded — DB row updated
                    # via job.failed/errors_list, structured WARNING with
                    # exc_info=True, and the loop continues. The traceback is
                    # preserved in the log; the per-game error string is
                    # persisted in errors_json for the admin UI.
                    # See docs/audits/error-handling-report.md §F-8.
                    except Exception as e:
                        failure_reason = _truncate_failure_reason(str(e))
                        await session.rollback()
                        # Re-fetch job after rollback
                        job_result = await session.execute(
                            select(BulkFlowGenerationJob).where(
                                BulkFlowGenerationJob.id == job_id
                            )
                        )
                        job = job_result.scalar_one()
                        job.failed += 1
                        errors_list.append(
                            {
                                "game_id": game.id,
                                "league": league_code,
                                "error": failure_reason,
                            }
                        )
                        await session.commit()
                        logger.warning(
                            "bulk_flow_failure",
                            extra={
                                "job_id": job_id,
                                "game_id": game.id,
                                "league": league_code,
                                "pbp_exists": True,
                                "goals_found": goals_found,
                                "flow_attempted": True,
                                "failure_reason": failure_reason,
                            },
                            exc_info=True,
                        )

                    # Small delay to avoid overwhelming the system
                    await asyncio.sleep(0.2)

                # Mark job as completed
                job.status = "completed"
                job.finished_at = datetime.utcnow()
                job.errors_json = errors_list
                await session.commit()

                logger.info(
                    f"Job {job_id} completed: "
                    f"{job.successful} successful, {job.failed} failed, "
                    f"{job.skipped} skipped"
                )

            # Top-level broad catch for the whole bulk loop. Any error not
            # already handled per-game (e.g. DB connection drop, query-side
            # failure) marks the job ``failed`` with the error captured in
            # ``errors_json``. ``logger.exception`` includes the traceback.
            # See docs/audits/error-handling-report.md §F-9.
            except Exception as e:
                # Mark job as failed on unexpected error
                logger.exception(f"Job {job_id} failed with unexpected error: {e}")
                await session.rollback()
                job_result = await session.execute(
                    select(BulkFlowGenerationJob).where(
                        BulkFlowGenerationJob.id == job_id
                    )
                )
                job = job_result.scalar_one_or_none()
                if job:
                    job.status = "failed"
                    job.finished_at = datetime.utcnow()
                    job.errors_json = [{"error": _truncate_failure_reason(str(e))}]
                    await session.commit()
    finally:
        # Clean up the engine to avoid connection leaks
        await engine.dispose()


@celery_app.task(name="run_bulk_flow_generation", bind=True)
def run_bulk_flow_generation(self, job_id: int) -> dict[str, Any]:
    """Celery task to run bulk game flow generation.

    This is a synchronous Celery task that wraps the async implementation.
    Job progress is tracked in the database, not Celery result backend.

    Args:
        job_id: Database ID of the BulkFlowGenerationJob record

    Returns:
        Summary dict with job_id and final status
    """
    logger.info(f"Celery task started for bulk flow job {job_id}")

    # Run the async function in a new event loop
    asyncio.run(_run_bulk_generation_async(job_id))

    return {"job_id": job_id, "status": "completed"}
