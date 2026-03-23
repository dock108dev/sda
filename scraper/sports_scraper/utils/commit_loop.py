"""SSOT commit-loop helper for all ingestion phases.

Every phase that iterates items and persists per-item should use this
instead of rolling its own try/commit/rollback/count loop.

Usage::

    from ..utils.commit_loop import commit_loop

    result = commit_loop(
        session,
        games,
        lambda s, g: _ingest_one(s, g),
        batch_size=1,              # per-game commit
        label="nhl_boxscores",
        max_consecutive_errors=10, # circuit breaker
    )
    summary["count"] = result.success
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TypeVar

from sqlalchemy.orm import Session

from ..logging import logger

T = TypeVar("T")


@dataclass
class LoopResult:
    """Counts returned by :func:`commit_loop`."""

    success: int = 0
    skipped: int = 0
    errors: int = 0
    skipped_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.success + self.skipped + self.errors


def commit_loop(
    session: Session,
    items: Iterable[T],
    process_fn: Callable[[Session, T], str],
    *,
    batch_size: int = 1,
    label: str = "commit_loop",
    max_consecutive_errors: int = 0,
) -> LoopResult:
    """Iterate *items*, call *process_fn* for each, and commit in batches.

    Parameters
    ----------
    session:
        SQLAlchemy session (caller manages lifecycle).
    items:
        Iterable of work items (games, snapshots, etc.).
    process_fn:
        ``(session, item) -> status_str``.  Must return one of:

        * ``"success"`` — item persisted, counts toward success.
        * ``"skipped"`` or ``"skipped:<reason>"`` — item intentionally
          skipped (e.g. no data available).  The part after the colon
          is tracked in ``LoopResult.skipped_reasons``.
        * Raising any exception counts as an error; the current batch
          is rolled back and processing continues.

    batch_size:
        How many successful items to accumulate before calling
        ``session.commit()``.  Use ``1`` for per-item commits (default),
        ``50`` for odds-style batching, etc.
    label:
        Name used in structured log messages.
    max_consecutive_errors:
        If > 0, stop iteration after this many consecutive errors
        (circuit breaker).  ``0`` disables the circuit breaker.
    """
    result = LoopResult()
    pending = 0  # items since last commit
    consecutive_errors = 0

    for item in items:
        # Circuit breaker
        if max_consecutive_errors and consecutive_errors >= max_consecutive_errors:
            logger.warning(
                f"{label}_circuit_breaker",
                consecutive_errors=consecutive_errors,
                processed=result.total,
                message=f"Stopping after {consecutive_errors} consecutive errors",
            )
            break

        try:
            status = process_fn(session, item)
        except Exception as exc:
            session.rollback()
            result.errors += 1
            consecutive_errors += 1
            pending = 0  # rollback cleared pending work
            logger.warning(
                f"{label}_item_error",
                error=str(exc),
                error_count=result.errors,
            )
            continue

        # Classify status
        if status == "success":
            result.success += 1
            consecutive_errors = 0
            pending += 1
        elif status and status.startswith("skipped"):
            result.skipped += 1
            consecutive_errors = 0  # skips are not failures
            reason = status.split(":", 1)[1] if ":" in status else "unknown"
            result.skipped_reasons[reason] = result.skipped_reasons.get(reason, 0) + 1
        elif status == "error":
            # process_fn returned error status instead of raising
            result.errors += 1
            consecutive_errors += 1
            pending += 1  # the writes may still be in the session
        else:
            # Unknown status — treat as skip
            result.skipped += 1
            logger.warning(f"{label}_unexpected_status", status=status)

        # Batch commit
        if pending and batch_size and pending >= batch_size:
            session.commit()
            pending = 0

    # Final commit for any remaining pending items
    if pending:
        session.commit()

    logger.info(
        f"{label}_complete",
        success=result.success,
        skipped=result.skipped,
        errors=result.errors,
        total=result.total,
        skipped_reasons=result.skipped_reasons or None,
    )

    return result
