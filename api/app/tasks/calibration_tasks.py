"""Celery task for training the sim probability calibration model.

Builds a dataset from historical predictions + closing lines, trains
an isotonic regression calibrator, and saves the artifact.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path

from app.celery_app import celery_app
from app.tasks._task_infra import _complete_job_run, _start_job_run, _task_db

logger = logging.getLogger(__name__)

# Default artifact directory (same pattern as model training)
_ARTIFACT_DIR = Path("artifacts/calibration")


@celery_app.task(name="train_calibration_model", bind=True, max_retries=0)
def train_calibration_model(self, sport: str = "mlb") -> dict:
    """Train a calibration model from historical sim predictions + outcomes.

    Args:
        sport: Sport code (default "mlb").

    Returns:
        Dict with training metrics or error.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_calibration_training(sport))
    finally:
        loop.close()


async def _run_calibration_training(sport: str) -> dict:
    """Async implementation of calibration model training."""
    from app.analytics.calibration.calibrator import SimCalibrator
    from app.analytics.calibration.dataset import build_calibration_dataset

    async with _task_db() as sf:
        run_id = await _start_job_run(
            sf, "calibration_training",
            summary_data={"sport": sport},
        )

        try:
            async with sf() as db:
                dataset = await build_calibration_dataset(db, sport)

            if len(dataset) < 20:
                msg = f"Insufficient data for calibration: {len(dataset)} rows (need 20+)"
                await _complete_job_run(sf, run_id, "error", msg)
                return {"error": msg, "dataset_size": len(dataset)}

            # Extract training arrays
            sim_wps = [r.sim_home_wp for r in dataset]
            actuals = [r.actual_home_win for r in dataset]

            # Train calibrator
            calibrator = SimCalibrator()
            metrics = calibrator.train(sim_wps, actuals)

            # Save artifact
            _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            artifact_path = _ARTIFACT_DIR / f"{sport}_calibrator_{timestamp}.joblib"
            calibrator.save(artifact_path)

            result = {
                "sport": sport,
                "artifact_path": str(artifact_path),
                "dataset_size": len(dataset),
                "brier_before": metrics.brier_before,
                "brier_after": metrics.brier_after,
                "brier_improvement": metrics.brier_improvement,
                "reliability_bins": metrics.reliability_bins,
            }

            await _complete_job_run(sf, run_id, "success", summary_data=result)
            logger.info("calibration_training_complete", extra=result)
            return result

        except Exception as exc:
            logger.exception("calibration_training_failed")
            await _complete_job_run(sf, run_id, "error", str(exc)[:500])
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[:2000],
            }
