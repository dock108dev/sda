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

            # Train each variant sequentially
            completed = 0
            failed = 0

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
                # Cache suite attrs — session expires objects after close
                suite_sport = suite.sport
                suite_model_type = suite.model_type

            for variant_row in variant_rows:
                try:
                    result = await _train_variant(sf, suite_sport, suite_model_type, variant_row)
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
    suite_sport: str,
    suite_model_type: str,
    variant: Any,
) -> dict:
    """Train a single experiment variant."""
    from app.db.analytics import AnalyticsExperimentVariant, AnalyticsTrainingJob

    # Create training job
    async with sf() as db:
        job = AnalyticsTrainingJob(
            sport=suite_sport,
            model_type=suite_model_type,
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


async def _generate_feature_loadouts(
    db: Any,
    feature_grid: dict[str, Any],
    suite: Any,
) -> list[int]:
    """Generate feature loadout combinations from a feature grid spec.

    The feature_grid contains:
      - features: list of {name, enabled, weight_min, weight_max} entries
      - max_combos: cap on number of generated loadouts (default 100)

    Strategy:
      1. Separate features into "fixed" (always on, single weight) and
         "variable" (toggled on/off or weight range).
      2. Generate combinations using Latin hypercube-style sampling
         for weight ranges, plus ablation sets (drop one feature at a time).
      3. Cap at max_combos, prioritizing diverse coverage.
    """
    import random

    from app.db.analytics import AnalyticsFeatureConfig

    features = feature_grid.get("features", [])
    max_combos = min(feature_grid.get("max_combos", 100), 1000)

    if not features:
        return []

    # Separate fixed vs variable features
    fixed: list[dict] = []
    variable: list[dict] = []
    for f in features:
        if not f.get("enabled", True):
            continue
        w_min = f.get("weight_min", f.get("weight", 1.0))
        w_max = f.get("weight_max", f.get("weight", 1.0))
        entry = {"name": f["name"], "weight_min": w_min, "weight_max": w_max}
        if w_min == w_max and f.get("vary_enabled") is not True:
            fixed.append(entry)
        else:
            variable.append(entry)

    if not variable:
        # No variation — just create one loadout with all fixed features
        loadout_features = [
            {"name": f["name"], "enabled": True, "weight": f["weight_min"]}
            for f in fixed
        ]
        row = AnalyticsFeatureConfig(
            name=f"exp-{suite.id}-baseline",
            sport=suite.sport,
            model_type=suite.model_type,
            features=loadout_features,
            is_default=False,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return [row.id]

    rng = random.Random(suite.id)  # deterministic per suite
    combos: list[list[dict]] = []

    def _mid(f: dict) -> float:
        return round((f["weight_min"] + f["weight_max"]) / 2, 2)

    def _rand_weight(f: dict) -> float:
        return round(rng.uniform(f["weight_min"], f["weight_max"]), 2)

    # 1. Baseline: all features on at midpoint weights
    combos.append([
        {"name": f["name"], "enabled": True, "weight": _mid(f)}
        for f in variable
    ])

    # 2. Ablation: drop each variable feature one at a time
    for i in range(len(variable)):
        ablation = []
        for j, f in enumerate(variable):
            if i == j:
                ablation.append({"name": f["name"], "enabled": False, "weight": 0})
            else:
                ablation.append({"name": f["name"], "enabled": True, "weight": _mid(f)})
        combos.append(ablation)

    # 3. Solo boost: one feature at max while others at midpoint
    for i, fi in enumerate(variable):
        if fi["weight_min"] == fi["weight_max"]:
            continue  # no weight range to boost
        solo = []
        for j, f in enumerate(variable):
            if i == j:
                solo.append({"name": f["name"], "enabled": True, "weight": f["weight_max"]})
            else:
                solo.append({"name": f["name"], "enabled": True, "weight": _mid(f)})
        combos.append(solo)

    # 4. Random samples — each feature gets an independent random weight
    budget = max_combos - len(combos)
    for _ in range(max(0, budget)):
        sample = []
        for f in variable:
            if f.get("vary_enabled"):
                # 15% chance of disabling when vary_enabled is on
                enabled = rng.random() > 0.15
            else:
                enabled = True
            weight = _rand_weight(f) if enabled else 0
            sample.append({"name": f["name"], "enabled": enabled, "weight": weight})
        combos.append(sample)

    # De-duplicate and cap
    seen: set[str] = set()
    unique_combos: list[list[dict]] = []
    for combo in combos:
        key = "|".join(f"{c['name']}:{c['enabled']}:{c['weight']}" for c in combo)
        if key not in seen:
            seen.add(key)
            unique_combos.append(combo)
        if len(unique_combos) >= max_combos:
            break

    # Create DB loadouts
    loadout_ids: list[int] = []
    for i, combo in enumerate(unique_combos):
        # Combine fixed features (always on) + variable features (from combo)
        all_features = [
            {"name": f["name"], "enabled": True, "weight": f["weight_min"]}
            for f in fixed
        ] + combo

        row = AnalyticsFeatureConfig(
            name=f"exp-{suite.id}-v{i}",
            sport=suite.sport,
            model_type=suite.model_type,
            features=all_features,
            is_default=False,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        loadout_ids.append(row.id)

    logger.info(
        "feature_loadouts_generated",
        extra={"suite_id": suite.id, "count": len(loadout_ids),
               "fixed": len(fixed), "variable": len(variable)},
    )
    return loadout_ids
