"""Golf pool auto-lock and auto-activation helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from ..logging import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_PRE_LOCK_STATUSES = ("draft", "open")
_PRE_LIVE_STATUSES = ("draft", "open", "locked")


def _auto_activate_pools(session: Session) -> list[dict[str, Any]]:
    """Auto-lock and auto-activate pools based on timestamps in rules_json.

    1. Pools in draft/open whose ``entry_deadline`` has passed → locked
    2. Pools in draft/open/locked whose ``rules_json->scoring_starts_at``
       has passed → live + scoring_enabled

    Returns list of activation events for logging.
    """
    now = datetime.now(UTC)
    events: list[dict[str, Any]] = []

    # --- Auto-lock: entry_deadline has passed ---
    rows = session.execute(
        text("""
            SELECT id, code, status, entry_deadline
            FROM golf_pools
            WHERE status IN ('draft', 'open')
              AND entry_deadline IS NOT NULL
              AND entry_deadline <= :now
        """),
        {"now": now},
    ).fetchall()

    for r in rows:
        pool_id, code, old_status = r[0], r[1], r[2]
        session.execute(
            text("""
                UPDATE golf_pools
                SET status = 'locked', updated_at = NOW()
                WHERE id = :id
            """),
            {"id": pool_id},
        )
        events.append({
            "pool_id": pool_id,
            "code": code,
            "action": "auto_locked",
            "from_status": old_status,
        })
        logger.info(
            "golf_pool_auto_locked",
            pool_id=pool_id,
            code=code,
            from_status=old_status,
            entry_deadline=str(r[3]),
        )

    # --- Auto-activate: scoring_starts_at has passed ---
    rows = session.execute(
        text("""
            SELECT id, code, status, rules_json
            FROM golf_pools
            WHERE status IN ('draft', 'open', 'locked')
              AND rules_json IS NOT NULL
              AND rules_json->>'scoring_starts_at' IS NOT NULL
        """),
    ).fetchall()

    for r in rows:
        pool_id, code, old_status, rules_json = r[0], r[1], r[2], r[3]
        starts_at_str = (rules_json or {}).get("scoring_starts_at")
        if not starts_at_str:
            continue

        try:
            starts_at = datetime.fromisoformat(starts_at_str)
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            logger.warning(
                "golf_pool_bad_scoring_starts_at",
                pool_id=pool_id,
                value=starts_at_str,
            )
            continue

        if now >= starts_at:
            session.execute(
                text("""
                    UPDATE golf_pools
                    SET status = 'live', scoring_enabled = TRUE, updated_at = NOW()
                    WHERE id = :id
                """),
                {"id": pool_id},
            )
            events.append({
                "pool_id": pool_id,
                "code": code,
                "action": "auto_activated",
                "from_status": old_status,
                "scoring_starts_at": starts_at_str,
            })
            logger.info(
                "golf_pool_auto_activated",
                pool_id=pool_id,
                code=code,
                from_status=old_status,
                scoring_starts_at=starts_at_str,
            )

    if events:
        session.commit()

    return events


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------
