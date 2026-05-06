"""Health / observability beat tasks.

These tasks emit health-of-the-system metrics rather than doing
ingestion work. They are short and side-effect-free apart from the
metric updates they push.
"""

from __future__ import annotations

from celery import shared_task
from sqlalchemy import text

from ..db import get_session
from ..db_health import init as init_pg_health_metrics
from ..db_health import update_max_idle_in_txn_age
from ..logging import logger

DEFAULT_QUEUE = "sports-scraper"


@shared_task(
    name="export_pg_idle_txn_metrics",
    # No autoretry: this is a periodic observability probe. If it fails
    # this minute, beat fires it again next minute. Stale metrics are
    # better than retries piling up behind broker errors.
)
def export_pg_idle_txn_metrics() -> dict:
    """Refresh the ``pg.idle_in_txn.max_age_seconds`` gauge per role.

    Runs every minute. Queries pg_stat_activity once, computes the
    oldest idle-in-transaction age per ``usename``, and writes those
    values into ``db_health``'s in-process cache. The OTel observable
    gauge callback reads from that cache on the next collection tick.

    Returns the same payload the metric exposes, for log inspection /
    ad-hoc verification via the Celery result backend.
    """
    init_pg_health_metrics()

    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT usename,
                       MAX(EXTRACT(EPOCH FROM (now() - xact_start)))::int AS max_age_s
                FROM pg_stat_activity
                WHERE state = 'idle in transaction'
                  AND xact_start IS NOT NULL
                  AND usename IS NOT NULL
                GROUP BY usename
                """
            )
        ).all()
        # Read-only query — close out the txn promptly so this exporter
        # itself is never the long-txn it's looking for.
        session.commit()

    payload: dict[str, int] = {}
    for role, max_age_s in rows:
        age = int(max_age_s or 0)
        update_max_idle_in_txn_age(role, age)
        payload[role] = age

    if payload:
        logger.debug("pg_idle_txn_metrics_exported", payload=payload)
    return payload
