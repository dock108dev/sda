"""Removed social dispatch phase.

Social collection is no longer part of the catch-up-only SDA scraper path.
Keep this module importable so old imports fail at call time with an explicit
SSOT error instead of breaking unrelated module collection.
"""

from __future__ import annotations

from datetime import datetime


def dispatch_social(
    run_id: int,
    config,
    summary: dict,
    start: datetime,
    end: datetime,
    supported_social_leagues: tuple,
    *,
    get_session,
    social_task_exists_fn,
    queue_job_run,
    enforce_social_queue_limit,
) -> None:
    """Fail hard for callers still trying to use the removed social path."""
    raise RuntimeError("Legacy path removed — use SSOT implementation")
