"""ORM event hooks: dispatch Celery tasks on Game.status lifecycle transitions.

Uses after_flush to detect FINAL transitions (while the session still tracks
attribute history) and after_commit to fire tasks only after the DB write is
durable.  after_rollback clears the pending list so aborted transactions never
dispatch tasks.

Thread-safety: _pending uses threading.local so concurrent requests each
maintain their own dispatch queue.
"""

from __future__ import annotations

import threading

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .sports import GameStatus, SportsGame
from . import external_id_validators as _ext_validators  # noqa: F401 — registers JSONB validators
from . import jsonb_validators as _jsonb_validators  # noqa: F401 — registers JSONB validators

_pending = threading.local()


def _get_pending() -> list[int]:
    """Return the per-thread list of game IDs pending dispatch."""
    if not hasattr(_pending, "game_ids"):
        _pending.game_ids = []
    return _pending.game_ids


@event.listens_for(Session, "after_flush")
def _track_final_transitions(session: Session, flush_context) -> None:
    """Collect game IDs whose status just transitioned to FINAL."""
    for obj in session.dirty:
        if not isinstance(obj, SportsGame):
            continue
        history = inspect(obj).attrs.status.history
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        if new == GameStatus.final.value and old != GameStatus.final.value:
            _get_pending().append(obj.id)


@event.listens_for(Session, "after_commit")
def _dispatch_final_game_tasks(session: Session) -> None:
    """Enqueue flow generation for each game that went FINAL in this commit."""
    pending = _get_pending()
    if not pending:
        return
    from ..celery_client import get_celery_app

    celery = get_celery_app()
    for game_id in pending:
        celery.send_task(
            "trigger_flow_for_game",
            args=[game_id],
            queue="sports-scraper",
            routing_key="sports-scraper",
            countdown=300,  # 5-minute delay so PBP data settles before pipeline runs
            expires=3600,  # drop task if not consumed within 1 hour; sweep handles recovery
        )
    pending.clear()


@event.listens_for(Session, "after_rollback")
def _clear_pending_on_rollback(session: Session) -> None:
    """Discard pending dispatch list when the transaction is rolled back."""
    _get_pending().clear()
