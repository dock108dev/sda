"""Edge-triggered flow generation: dispatch when a game goes final.

Instead of generating flows on a fixed schedule hours after ingestion,
we trigger flow generation as soon as a game transitions live → final
and has sufficient PBP data.

State machine:
  FINAL → RECAP_PENDING  (on dispatch / task start)
  RECAP_PENDING → RECAP_READY   (on pipeline success)
  RECAP_PENDING → RECAP_FAILED  (on error; eligible for sweep retry)

sweep_missing_flows() is the safety-net: a daily task that finds any
FINAL or RECAP_FAILED games from the past 24 h with no flow artifact
and re-enqueues trigger_flow_for_game for each.

backfill_missing_flows() is a one-shot Phase-1 deploy task that covers
the past N days (default 7). Safe to re-run: the NX lock inside
trigger_flow_for_game prevents double-dispatch.
"""

from __future__ import annotations

from celery import shared_task

from ..db import get_session
from ..logging import logger

# Valid statuses for flow dispatch: newly final, already in-progress, or previously failed.
_VALID_DISPATCH_STATUSES = frozenset({"final", "recap_pending", "recap_failed"})


def _set_game_status(game_id: int, status: str) -> None:
    """Update game.status in a new DB session; errors are logged, not raised."""
    from ..db import db_models

    try:
        with get_session() as session:
            game = session.query(db_models.SportsGame).get(game_id)
            if game:
                game.status = status
    except Exception:
        logger.exception("set_game_status_failed", game_id=game_id, status=status)


@shared_task(
    name="trigger_flow_for_game",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    # Retry schedule: 5 min, 15 min, 30 min
    default_retry_delay=300,
)
def trigger_flow_for_game(game_id: int) -> dict:
    """Generate flows for a single game that just went final.

    Steps:
    1. Verify game is in a dispatchable status (final / recap_pending / recap_failed)
    2. Mark status as RECAP_PENDING (in-progress signal)
    3. Call the API pipeline endpoint
    4. Mark RECAP_READY on success, RECAP_FAILED on error

    Args:
        game_id: The sports_games.id to generate flows for

    Returns:
        dict with generation result
    """
    from sqlalchemy import exists

    from ..db import db_models
    from ..services.job_runs import complete_job_run, start_job_run
    from ..utils.redis_lock import LOCK_TIMEOUT_1HOUR, acquire_redis_lock, release_redis_lock

    # Acquire lock before any pipeline work — key format: pipeline_lock:{task_type}:{game_id}
    lock_name = f"pipeline_lock:trigger_flow_for_game:{game_id}"
    lock_token = acquire_redis_lock(lock_name, timeout=LOCK_TIMEOUT_1HOUR)
    if not lock_token:
        logger.info("flow_trigger_skipped_locked", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "locked"}

    with get_session() as session:
        game = session.query(db_models.SportsGame).get(game_id)

        if not game:
            logger.warning("flow_trigger_game_not_found", game_id=game_id)
            return {"game_id": game_id, "status": "not_found"}

        if game.status not in _VALID_DISPATCH_STATUSES:
            logger.info(
                "flow_trigger_skip_not_eligible",
                game_id=game_id,
                status=game.status,
            )
            return {"game_id": game_id, "status": "skipped", "reason": "not_eligible"}

        # Mark in-progress atomically in the same session block
        game.status = db_models.GameStatus.recap_pending.value
        league_id = game.league_id

        # Check if game has PBP data
        has_pbp = session.query(
            exists().where(db_models.SportsGamePlay.game_id == game_id)
        ).scalar()

        if not has_pbp:
            logger.warning(
                "flow_trigger_no_pbp",
                game_id=game_id,
            )
            # Retry will kick in via Celery's autoretry; TTL expiry releases the lock
            raise Exception(f"Game {game_id} has no PBP data yet — will retry")

    job_run_id = start_job_run("trigger_flow", [])
    try:
        with get_session() as session:
            # Check if flows already exist (skip if so)
            has_artifacts = session.query(
                exists().where(db_models.SportsGameTimelineArtifact.game_id == game_id)
            ).scalar()

            if has_artifacts:
                logger.info(
                    "flow_trigger_skip_immutable",
                    game_id=game_id,
                )
                complete_job_run(
                    job_run_id,
                    status="success",
                    summary_data={"game_id": game_id, "skipped": "immutable"},
                )
                _set_game_status(game_id, db_models.GameStatus.recap_ready.value)
                release_redis_lock(lock_name, lock_token)
                return {"game_id": game_id, "status": "skipped", "reason": "immutable"}

            # Get league code for the API call
            league = session.query(db_models.SportsLeague).get(league_id)
            league_code = league.code if league else "UNKNOWN"

        # Call the API pipeline endpoint (outside session)
        result = _call_pipeline_api(game_id, league_code)
        complete_job_run(
            job_run_id,
            status="success" if result.get("status") == "success" else "error",
            summary_data={"game_id": game_id, "league": league_code},
            error_summary=result.get("error"),
        )
        _set_game_status(game_id, db_models.GameStatus.recap_ready.value)
        # Release only on success; on failure TTL expiry is the safety net
        release_redis_lock(lock_name, lock_token)
        return result
    except Exception as exc:
        complete_job_run(job_run_id, status="error", error_summary=str(exc)[:500])
        _set_game_status(game_id, db_models.GameStatus.recap_failed.value)
        raise


def _call_pipeline_api(game_id: int, league_code: str) -> dict:
    """Call the internal API to generate flows for a single game."""
    import httpx

    from ..api_client import get_api_headers
    from ..config import settings

    api_base = settings.api_internal_url

    logger.info(
        "flow_trigger_api_call",
        game_id=game_id,
        league=league_code,
    )

    try:
        with httpx.Client(timeout=120.0, headers=get_api_headers()) as client:
            response = client.post(
                f"{api_base}/api/admin/sports/pipeline/{game_id}/run-full",
                json={"triggered_by": "edge_trigger"},
            )
            response.raise_for_status()
            result = response.json()

        logger.info(
            "flow_trigger_success",
            game_id=game_id,
            league=league_code,
            result=result,
        )
        return {
            "game_id": game_id,
            "league": league_code,
            "status": "success",
            "result": result,
        }

    except httpx.HTTPStatusError as exc:
        logger.error(
            "flow_trigger_http_error",
            game_id=game_id,
            league=league_code,
            status_code=exc.response.status_code,
            error=exc.response.text,
        )
        # Don't retry on 4xx errors (bad request, not found)
        if 400 <= exc.response.status_code < 500:
            return {
                "game_id": game_id,
                "league": league_code,
                "status": "error",
                "error": f"HTTP {exc.response.status_code}",
            }
        raise  # 5xx errors will trigger Celery retry

    except Exception as exc:
        logger.exception(
            "flow_trigger_error",
            game_id=game_id,
            league=league_code,
            error=str(exc),
        )
        raise  # Let Celery retry


@shared_task(name="sweep_missing_flows")
def sweep_missing_flows() -> dict:
    """Safety-net sweep: enqueue flow generation for eligible games with no artifact.

    Targets FINAL games (hook may have misfired) and RECAP_FAILED games (prior
    attempt failed; NX lock has since expired). Runs daily.

    Returns:
        dict with count of game IDs enqueued.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import not_, or_
    from sqlalchemy import exists as sa_exists

    from ..db import db_models
    from ..utils.redis_lock import LOCK_TIMEOUT_5MIN, acquire_redis_lock, release_redis_lock

    SWEEP_LOCK = "flow:sweep:lock"
    lock_token = acquire_redis_lock(SWEEP_LOCK, timeout=LOCK_TIMEOUT_5MIN)
    if not lock_token:
        logger.info("sweep_missing_flows_skipped_locked")
        return {"status": "skipped", "reason": "locked"}

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        with get_session() as session:
            games = (
                session.query(db_models.SportsGame)
                .filter(
                    or_(
                        db_models.SportsGame.status == db_models.GameStatus.final.value,
                        db_models.SportsGame.status == db_models.GameStatus.recap_failed.value,
                    ),
                    db_models.SportsGame.game_date >= cutoff,
                    not_(
                        sa_exists().where(
                            db_models.SportsGameTimelineArtifact.game_id
                            == db_models.SportsGame.id
                        )
                    ),
                )
                .all()
            )
            game_ids = [g.id for g in games]

        for game_id in game_ids:
            trigger_flow_for_game.delay(game_id)
            logger.info("sweep_missing_flows_enqueued", game_id=game_id)

        logger.info("sweep_missing_flows_complete", enqueued=len(game_ids))
        return {"status": "success", "enqueued": len(game_ids)}
    finally:
        release_redis_lock(SWEEP_LOCK, lock_token)


# Stagger interval between enqueued backfill tasks (seconds)
_BACKFILL_STAGGER_SECONDS = 30


@shared_task(name="backfill_missing_flows")
def backfill_missing_flows(dry_run: bool = False, days: int = 7) -> dict:
    """One-shot backfill: enqueue flow generation for FINAL/RECAP_FAILED games missing a flow.

    Designed for Phase 1 deploy. Safe to re-run — the NX lock inside
    trigger_flow_for_game prevents double-dispatch.

    Args:
        dry_run: When True, log the games that would be enqueued but do not enqueue.
        days: Look-back window in days (default 7).

    Returns:
        dict with ``found``, ``enqueued`` (or ``would_enqueue`` in dry-run), and ``status``.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import not_, or_
    from sqlalchemy import exists as sa_exists

    from ..db import db_models
    from ..utils.redis_lock import LOCK_TIMEOUT_10MIN, acquire_redis_lock, release_redis_lock

    BACKFILL_LOCK = "flow:backfill:lock"
    lock_token = acquire_redis_lock(BACKFILL_LOCK, timeout=LOCK_TIMEOUT_10MIN)
    if not lock_token:
        logger.info("backfill_missing_flows_skipped_locked", dry_run=dry_run, days=days)
        return {"status": "skipped", "reason": "locked"}

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with get_session() as session:
            games = (
                session.query(db_models.SportsGame)
                .filter(
                    or_(
                        db_models.SportsGame.status == db_models.GameStatus.final.value,
                        db_models.SportsGame.status == db_models.GameStatus.recap_failed.value,
                    ),
                    db_models.SportsGame.game_date >= cutoff,
                    not_(
                        sa_exists().where(
                            db_models.SportsGameTimelineArtifact.game_id
                            == db_models.SportsGame.id
                        )
                    ),
                )
                .all()
            )
            game_ids = [g.id for g in games]

        logger.info(
            "backfill_missing_flows_found",
            found=len(game_ids),
            dry_run=dry_run,
            days=days,
        )

        if dry_run:
            logger.info(
                "backfill_missing_flows_dry_run",
                game_ids=game_ids,
                would_enqueue=len(game_ids),
            )
            return {"status": "dry_run", "found": len(game_ids), "would_enqueue": len(game_ids)}

        for idx, game_id in enumerate(game_ids):
            countdown = idx * _BACKFILL_STAGGER_SECONDS
            trigger_flow_for_game.apply_async(args=[game_id], countdown=countdown)
            logger.info(
                "backfill_missing_flows_enqueued",
                game_id=game_id,
                countdown_seconds=countdown,
            )

        logger.info(
            "backfill_missing_flows_complete",
            found=len(game_ids),
            enqueued=len(game_ids),
        )
        return {"status": "success", "found": len(game_ids), "enqueued": len(game_ids)}
    finally:
        release_redis_lock(BACKFILL_LOCK, lock_token)
