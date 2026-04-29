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

from sqlalchemy import and_, func, select
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

                result = await session.execute(query)
                games = result.scalars().all()

                # Filter to games that have PBP data
                games_with_pbp = []
                for game in games:
                    pbp_count = await session.execute(
                        select(func.count(SportsGamePlay.id)).where(
                            SportsGamePlay.game_id == game.id
                        )
                    )
                    if (pbp_count.scalar() or 0) > 0:
                        games_with_pbp.append(game)

                # Apply max_games limit if specified
                if job.max_games is not None and job.max_games > 0:
                    games_with_pbp = games_with_pbp[: job.max_games]
                    logger.info(
                        f"Job {job_id}: Limited to {job.max_games} games (max_games)"
                    )

                job.total_games = len(games_with_pbp)
                await session.commit()

                logger.info(f"Job {job_id}: Found {len(games_with_pbp)} games with PBP")

                errors_list: list[dict[str, Any]] = []

                for i, game in enumerate(games_with_pbp):
                    job.current_game = i + 1
                    await session.commit()

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
                            f"Job {job_id}: Generated game flow for game {game.id}"
                        )
                    except Exception as e:
                        await session.rollback()
                        # Re-fetch job after rollback
                        job_result = await session.execute(
                            select(BulkFlowGenerationJob).where(
                                BulkFlowGenerationJob.id == job_id
                            )
                        )
                        job = job_result.scalar_one()
                        job.failed += 1
                        errors_list.append({"game_id": game.id, "error": str(e)})
                        await session.commit()
                        logger.warning(f"Job {job_id}: Failed game {game.id}: {e}")

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
                    job.errors_json = [{"error": str(e)}]
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
