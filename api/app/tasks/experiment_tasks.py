"""Celery tasks for experiment suite orchestration.

Launches a grid of model training variants, optionally followed by
historical replay, and ranks the results.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import UTC, datetime

from app.celery_app import celery_app
from app.tasks._experiment_suite_helpers import (
    _build_leaderboard,
    _dispatch_variant_training,
    _generate_feature_loadouts,
    _generate_variants,
    _poll_variant_completion,
)
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)


@celery_app.task(
    name="run_experiment_suite",
    bind=True,
    max_retries=0,
    soft_time_limit=43200,  # 12 hours — experiments train many models sequentially
    time_limit=43500,       # hard kill 5 min after soft
)
def run_experiment_suite(self, suite_id: int) -> dict:
    """Launch an experiment suite: train variants, replay, rank."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_suite(suite_id, self.request.id))
    finally:
        loop.close()


async def _run_suite(suite_id: int, celery_task_id: str | None = None) -> dict:
    """Async implementation of experiment suite orchestration."""
    from app.db.analytics import (
        AnalyticsExperimentSuite,
        AnalyticsExperimentVariant,
    )

    async with _task_db() as sf:
        run_id = await _start_job_run(
            sf, "analytics_experiment", celery_task_id,
            summary_data={"suite_id": suite_id},
        )

        # Load suite and generate variants
        async with sf() as db:
            suite = await db.get(AnalyticsExperimentSuite, suite_id)
            if suite is None:
                await _complete_job_run(sf, run_id, "error", "suite_not_found")
                return {"error": "suite_not_found"}

            suite.status = "running"
            if celery_task_id:
                suite.celery_task_id = celery_task_id
            await db.commit()

        try:
            # Generate variant combinations from parameter grid
            async with sf() as db:
                suite = await db.get(AnalyticsExperimentSuite, suite_id)
                grid = suite.parameter_grid or {}

                # If feature_grid is present, generate loadout combos first
                feature_config_ids = grid.get("feature_config_ids", [None])
                feature_grid = grid.get("feature_grid")
                if feature_grid:
                    generated_ids = await _generate_feature_loadouts(
                        db, feature_grid, suite,
                    )
                    feature_config_ids = generated_ids or [None]
                    grid["feature_config_ids"] = feature_config_ids

                variants = _generate_variants(grid, suite)

                suite.total_variants = len(variants)
                await db.commit()

                # Create variant rows
                for i, params in enumerate(variants):
                    variant = AnalyticsExperimentVariant(
                        suite_id=suite_id,
                        variant_index=i,
                        algorithm=params["algorithm"],
                        rolling_window=params.get("rolling_window", 30),
                        feature_config_id=params.get("feature_config_id"),
                        training_date_start=params.get("date_start"),
                        training_date_end=params.get("date_end"),
                        test_split=params.get("test_split", 0.2),
                        extra_params=params.get("extra_params"),
                        status="pending",
                    )
                    db.add(variant)
                await db.commit()

            # Dispatch variant training as parallel Celery tasks
            async with sf() as db:
                from sqlalchemy import select
                suite = await db.get(AnalyticsExperimentSuite, suite_id)
                stmt = (
                    select(AnalyticsExperimentVariant)
                    .where(AnalyticsExperimentVariant.suite_id == suite_id)
                    .order_by(AnalyticsExperimentVariant.variant_index)
                )
                result_rows = await db.execute(stmt)
                variant_rows = list(result_rows.scalars().all())
                suite_sport = suite.sport
                suite_model_type = suite.model_type

            # Create training jobs and dispatch to worker pool
            variant_jobs: list[tuple[int, int, str]] = []  # (variant_id, job_id, celery_task_id)
            dispatch_failures = 0
            for variant_row in variant_rows:
                try:
                    v_id, job_id, task_id = await _dispatch_variant_training(
                        sf, suite_sport, suite_model_type, variant_row,
                    )
                    variant_jobs.append((v_id, job_id, task_id))
                except Exception as exc:
                    logger.warning(
                        "variant_dispatch_failed",
                        extra={"variant_id": variant_row.id, "error": str(exc)},
                    )
                    dispatch_failures += 1

            logger.info(
                "experiment_variants_dispatched",
                extra={"suite_id": suite_id, "count": len(variant_jobs)},
            )

            # Poll until all variants are done — progress updated in DB inline
            completed, failed = await _poll_variant_completion(
                sf, suite_id, variant_jobs,
            )

            # Build leaderboard
            leaderboard = await _build_leaderboard(sf, suite_id)

            async with sf() as db:
                s = await db.get(AnalyticsExperimentSuite, suite_id)
                if s:
                    s.status = "completed"
                    s.leaderboard = leaderboard
                    s.completed_at = datetime.now(UTC)
                    await db.commit()

            summary = {
                "suite_id": suite_id,
                "total": len(variants),
                "completed": completed,
                "failed": failed,
            }
            await _complete_job_run(sf, run_id, "success", summary_data=summary)
            return summary

        except Exception as exc:
            logger.exception("experiment_suite_failed", extra={"suite_id": suite_id})
            async with sf() as db:
                s = await db.get(AnalyticsExperimentSuite, suite_id)
                if s:
                    s.status = "failed"
                    s.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                    s.completed_at = datetime.now(UTC)
                    await db.commit()
            await _complete_job_run(sf, run_id, "error", str(exc)[:500])
            return {"error": str(exc)}
