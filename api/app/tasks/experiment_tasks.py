"""Celery tasks for experiment suite orchestration.

Launches a grid of model training variants, optionally followed by
historical replay, and ranks the results.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import traceback
from datetime import UTC, datetime
from typing import Any

from app.celery_app import celery_app
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)


@celery_app.task(name="run_experiment_suite", bind=True, max_retries=0)
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

            # Train each variant sequentially
            completed = 0
            failed = 0

            async with sf() as db:
                suite = await db.get(AnalyticsExperimentSuite, suite_id)
                variant_rows = list(suite.variants)

            for variant_row in variant_rows:
                try:
                    result = await _train_variant(sf, suite, variant_row)
                    if "error" in result:
                        failed += 1
                    else:
                        completed += 1
                except Exception as exc:
                    logger.exception(
                        "variant_failed",
                        extra={"variant_id": variant_row.id, "error": str(exc)},
                    )
                    async with sf() as db:
                        v = await db.get(AnalyticsExperimentVariant, variant_row.id)
                        if v:
                            v.status = "failed"
                            v.error_message = str(exc)[:500]
                            v.completed_at = datetime.now(UTC)
                            await db.commit()
                    failed += 1

                # Update suite progress
                async with sf() as db:
                    s = await db.get(AnalyticsExperimentSuite, suite_id)
                    if s:
                        s.completed_variants = completed
                        s.failed_variants = failed
                        await db.commit()

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


def _generate_variants(
    grid: dict[str, Any],
    suite: Any,
) -> list[dict[str, Any]]:
    """Generate variant parameter combinations from a grid spec."""
    algorithms = grid.get("algorithms", ["gradient_boosting"])
    rolling_windows = grid.get("rolling_windows", [30])
    feature_config_ids = grid.get("feature_config_ids", [None])
    test_splits = grid.get("test_splits", [0.2])
    date_start = grid.get("date_start")
    date_end = grid.get("date_end")

    combos = list(itertools.product(
        algorithms, rolling_windows, feature_config_ids, test_splits
    ))

    variants = []
    for algo, window, config_id, split in combos:
        variants.append({
            "algorithm": algo,
            "rolling_window": window,
            "feature_config_id": config_id,
            "test_split": split,
            "date_start": date_start,
            "date_end": date_end,
        })

    return variants


async def _train_variant(
    sf: Any,
    suite: Any,
    variant: Any,
) -> dict:
    """Train a single experiment variant."""
    from app.db.analytics import AnalyticsExperimentVariant, AnalyticsTrainingJob

    # Create training job
    async with sf() as db:
        job = AnalyticsTrainingJob(
            sport=suite.sport,
            model_type=suite.model_type,
            algorithm=variant.algorithm,
            feature_config_id=variant.feature_config_id,
            date_start=variant.training_date_start,
            date_end=variant.training_date_end,
            test_split=variant.test_split,
            rolling_window=variant.rolling_window,
            status="pending",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    # Run training inline (not dispatching to Celery — we're already in a task)
    from app.tasks.training_tasks import _run_training

    result = await _run_training(job_id)

    # Update variant with results
    async with sf() as db:
        v = await db.get(AnalyticsExperimentVariant, variant.id)
        if v:
            v.training_job_id = job_id
            if "error" in result:
                v.status = "failed"
                v.error_message = result.get("error", "unknown")
            else:
                v.status = "completed"
                v.model_id = result.get("model_id")
                v.training_metrics = result.get("metrics")
            v.completed_at = datetime.now(UTC)
            await db.commit()

    return result


async def _build_leaderboard(
    sf: Any,
    suite_id: int,
) -> list[dict[str, Any]]:
    """Build ranked leaderboard from completed variants."""
    from sqlalchemy import select

    from app.db.analytics import AnalyticsExperimentVariant

    async with sf() as db:
        stmt = (
            select(AnalyticsExperimentVariant)
            .where(
                AnalyticsExperimentVariant.suite_id == suite_id,
                AnalyticsExperimentVariant.status == "completed",
            )
        )
        result = await db.execute(stmt)
        variants = result.scalars().all()

    # Sort by accuracy desc, then brier score asc
    entries = []
    for v in variants:
        metrics = v.training_metrics or {}
        entries.append({
            "variant_id": v.id,
            "variant_index": v.variant_index,
            "algorithm": v.algorithm,
            "rolling_window": v.rolling_window,
            "model_id": v.model_id,
            "accuracy": metrics.get("accuracy"),
            "brier_score": metrics.get("brier_score"),
            "log_loss": metrics.get("log_loss"),
            "replay_metrics": v.replay_metrics,
        })

    entries.sort(
        key=lambda e: (
            -(e.get("accuracy") or 0),
            e.get("brier_score") or 999,
        )
    )

    # Assign ranks
    for i, entry in enumerate(entries):
        entry["rank"] = i + 1

    # Persist ranks back
    async with sf() as db:
        for entry in entries:
            v = await db.get(AnalyticsExperimentVariant, entry["variant_id"])
            if v:
                v.rank = entry["rank"]
        await db.commit()

    return entries
