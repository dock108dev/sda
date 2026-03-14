"""Shared task infrastructure for analytics Celery tasks.

Provides job-run tracking helpers and an async DB context manager
that creates a fresh engine per task invocation (avoiding event-loop
conflicts with the module-level engine).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job-run tracking helpers (writes to sports_job_runs so analytics tasks
# appear in the shared Runs drawer alongside scraper tasks).
# ---------------------------------------------------------------------------


async def _start_job_run(
    sf,
    phase: str,
    celery_task_id: str | None = None,
    summary_data: dict[str, Any] | None = None,
) -> int:
    """Create a SportsJobRun row with status='running' and return its ID."""
    # Import all models referenced by string relationships on SportsGame
    # so SQLAlchemy's mapper configuration can resolve them.
    import app.db.flow  # noqa: F401
    import app.db.mlb_advanced  # noqa: F401
    import app.db.odds  # noqa: F401
    import app.db.social  # noqa: F401
    from app.db.scraper import SportsJobRun

    async with sf() as db:
        run = SportsJobRun(
            phase=phase,
            leagues=[],  # analytics tasks aren't league-scoped
            status="running",
            started_at=datetime.now(UTC),
            celery_task_id=celery_task_id,
            summary_data=summary_data,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return int(run.id)


async def _complete_job_run(
    sf,
    run_id: int,
    status: str,
    error_summary: str | None = None,
    summary_data: dict[str, Any] | None = None,
) -> None:
    """Finalize a SportsJobRun row with status + duration."""
    from app.db.scraper import SportsJobRun  # mapper deps loaded by _start_job_run

    async with sf() as db:
        run = await db.get(SportsJobRun, run_id)
        if not run:
            return
        if run.status == "canceled":
            # Cancellation is terminal. Keep the canceled status even if the
            # worker reaches normal completion/error handling paths.
            logger.info(
                "analytics_job_run_completion_skipped_canceled",
                extra={"run_id": run_id, "attempted_status": status},
            )
            return
        finished = datetime.now(UTC)
        run.status = status
        run.finished_at = finished
        run.duration_seconds = (finished - run.started_at).total_seconds()
        run.error_summary = error_summary
        if summary_data is not None:
            run.summary_data = summary_data
        await db.commit()


@asynccontextmanager
async def _task_db():
    """Create a fresh async engine + session factory bound to the current loop.

    Celery tasks run in a new event loop per invocation.  The module-level
    engine in ``app.db`` binds its connection-pool futures to the loop that
    created it, so reusing it from a different loop raises
    "Future attached to a different loop".  Following the pattern in
    ``bulk_flow_generation.py``, we create a throwaway engine here and
    dispose of it when the task finishes.

    Yields a session factory -- callers open/close individual sessions via
    ``async with sf() as db: ...`` as needed.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    engine = create_async_engine(settings.database_url, echo=False, future=True)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    try:
        yield factory
    finally:
        await engine.dispose()
