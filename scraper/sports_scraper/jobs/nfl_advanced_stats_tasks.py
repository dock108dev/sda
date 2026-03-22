"""Celery task for ingesting NFL nflverse-derived advanced stats."""

from __future__ import annotations

from celery import shared_task

from ..db import get_session


@shared_task(
    name="ingest_nfl_advanced_stats",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    default_retry_delay=300,
)
def ingest_nfl_advanced_stats(game_id: int) -> dict:
    """Ingest nflverse-derived advanced stats for an NFL game.

    Dispatched when a game goes final (with 60s countdown).

    Args:
        game_id: The sports_games.id to ingest stats for.

    Returns:
        Dict with ingestion result.
    """
    from ..services.job_runs import complete_job_run, start_job_run
    from ..services.nfl_advanced_stats_ingestion import ingest_advanced_stats_for_game

    job_run_id = start_job_run("ingest_nfl_advanced_stats", [])
    try:
        with get_session() as session:
            result = ingest_advanced_stats_for_game(session, game_id)

        complete_job_run(
            job_run_id,
            status="success" if result.get("status") == "success" else "skipped",
            summary_data=result,
        )
        return result
    except Exception as exc:
        complete_job_run(job_run_id, status="error", error_summary=str(exc)[:500])
        raise
