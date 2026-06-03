"""Sports game status normalization and transition policy."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..db import db_models
from ..utils.datetime_utils import now_utc


def _normalize_status(status: str | None) -> str:
    if not status:
        return db_models.GameStatus.scheduled.value
    status_normalized = status.lower()
    if status_normalized in {"final", "completed"}:
        return db_models.GameStatus.final.value
    if status_normalized == db_models.GameStatus.live.value:
        return db_models.GameStatus.live.value
    if status_normalized == db_models.GameStatus.pregame.value:
        return db_models.GameStatus.pregame.value
    if status_normalized == db_models.GameStatus.archived.value:
        return db_models.GameStatus.archived.value
    if status_normalized == db_models.GameStatus.scheduled.value:
        return db_models.GameStatus.scheduled.value
    if status_normalized == db_models.GameStatus.postponed.value:
        return db_models.GameStatus.postponed.value
    if status_normalized in {db_models.GameStatus.CANCELLED.value, "canceled"}:
        return db_models.GameStatus.CANCELLED.value
    if status_normalized == db_models.GameStatus.recap_pending.value:
        return db_models.GameStatus.recap_pending.value
    if status_normalized == db_models.GameStatus.recap_ready.value:
        return db_models.GameStatus.recap_ready.value
    if status_normalized == db_models.GameStatus.recap_failed.value:
        return db_models.GameStatus.recap_failed.value
    return db_models.GameStatus.scheduled.value


# One-way progression order for the happy path.
# Higher index = further along in lifecycle. Transitions may only move forward.
# recap_* statuses sit between final and archived: they imply final has been
# reached, so they must not regress to live/pregame/scheduled.
_STATUS_ORDER: dict[str, int] = {
    db_models.GameStatus.scheduled.value: 0,
    db_models.GameStatus.pregame.value: 1,
    db_models.GameStatus.live.value: 2,
    db_models.GameStatus.final.value: 3,
    db_models.GameStatus.recap_pending.value: 4,
    db_models.GameStatus.recap_failed.value: 4,
    db_models.GameStatus.recap_ready.value: 5,
    db_models.GameStatus.archived.value: 6,
}


# Margin before scheduled tipoff during which a stuck `live` game is allowed
# to self-heal back to pregame/scheduled. Set conservatively so a true live
# game whose scoreboard briefly reports "preview" near tipoff is never demoted.
_LIVE_SELF_HEAL_MARGIN = timedelta(minutes=15)


def resolve_status_transition(
    current_status: str | None,
    incoming_status: str | None,
    *,
    game_date: datetime | None = None,
    now: datetime | None = None,
) -> str:
    """Resolve a safe status transition without regressing games.

    Rules:
    - archived is terminal (never regresses from archived)
    - final and post-final (recap_*) never regress to pre-final states; they
      only move forward within the post-final lane
    - Generally, status only moves forward in the lifecycle
    - Non-lifecycle statuses (postponed, cancelled) are accepted as-is

    Self-heal: a `live` game that the upstream feed now reports as
    pregame/scheduled is allowed to regress, but only when ``game_date``
    is comfortably in the future (>15min from ``now``). This recovers
    games that were wrongly promoted to live by spurious upstream signals
    without undoing a correct promotion that briefly flickered near tipoff.
    """
    current = _normalize_status(current_status)
    incoming = _normalize_status(incoming_status)

    # Terminal states: archived never regresses
    if current == db_models.GameStatus.archived.value:
        return current

    # Once a game has reached final (or any post-final state), it can only
    # advance within the post-final lane. Pre-final incoming statuses
    # (scheduled/pregame/live) are stale signals and must be ignored.
    if db_models.GameStatus.is_final_or_post_final_status(current):
        if db_models.GameStatus.is_final_or_post_final_status(incoming):
            current_order = _STATUS_ORDER.get(current)
            incoming_order = _STATUS_ORDER.get(incoming)
            if current_order is not None and incoming_order is not None:
                if incoming_order < current_order:
                    return current
                return incoming
        return current

    # For lifecycle states, only allow forward progression — except for the
    # narrow self-heal escape hatch: live → pregame/scheduled is allowed when
    # tipoff is still meaningfully in the future, since "live before tipoff"
    # is necessarily a past write error.
    current_order = _STATUS_ORDER.get(current)
    incoming_order = _STATUS_ORDER.get(incoming)

    if current_order is not None and incoming_order is not None:
        if incoming_order < current_order:
            if (
                current == db_models.GameStatus.live.value
                and incoming
                in (
                    db_models.GameStatus.pregame.value,
                    db_models.GameStatus.scheduled.value,
                )
                and game_date is not None
            ):
                _now = now if now is not None else now_utc()
                if game_date > _now + _LIVE_SELF_HEAL_MARGIN:
                    return incoming
            return current  # Don't regress
        return incoming

    # Non-lifecycle statuses (postponed, cancelled) pass through
    return incoming


def merge_external_ids(
    existing: dict[str, Any],
    updates: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge external IDs, preferring new non-null values."""
    if not updates:
        return existing

    merged = dict(existing or {})
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    return merged
