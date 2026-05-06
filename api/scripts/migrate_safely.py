"""Self-coordinating Alembic runner for the migrate container.

Workflow:
1. Set the ``sports:tasks_held`` Redis flag so beat-scheduled tasks skip.
2. Wait up to ``MIGRATE_DRAIN_TIMEOUT`` seconds for in-flight non-alembic
   ``dock108`` transactions to drain. This avoids the lock-queue scenario
   where a worker holding ``AccessShareLock`` on a hot table blocks the
   migration's ``ALTER TABLE`` and stacks every subsequent worker query
   behind it.
3. Run ``alembic -c /app/alembic.ini upgrade head`` (configurable via
   ``MIGRATE_COMMAND``).
4. Always clear the hold switch on exit (success *or* failure).

Drains are best-effort: if the timeout expires the script logs which
sessions are still open and proceeds with the migration anyway, so the
operator still sees alembic's behavior rather than silently aborting.

Environment:
    DATABASE_URL            Required. Same URL the rest of the app uses.
    REDIS_URL               Optional. If unset, hold-switch step is skipped.
    MIGRATE_DRAIN_TIMEOUT   Optional, seconds (default 120).
    MIGRATE_COMMAND         Optional shell-style command. Default:
                            ``alembic -c /app/alembic.ini upgrade head``.
    MIGRATE_HOLD_KEY        Optional Redis key (default ``sports:tasks_held``).
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import time
from contextlib import suppress
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import redis  # type: ignore[import-untyped]

_DEFAULT_DRAIN_TIMEOUT = 120
_DEFAULT_HOLD_KEY = "sports:tasks_held"
_DEFAULT_COMMAND = "alembic -c /app/alembic.ini upgrade head"
_APP_ROLE = "dock108"


def _log(msg: str) -> None:
    """Stdout log with a [migrate_safely] prefix so it's distinguishable
    from the alembic output that follows."""
    print(f"[migrate_safely] {msg}", flush=True)


def _to_asyncpg_url(database_url: str) -> str:
    """SQLAlchemy uses ``postgresql+asyncpg://`` but asyncpg's own connect()
    wants the bare ``postgresql://`` form."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _open_app_txns(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Return non-alembic, non-self ``dock108`` sessions that are mid-txn."""
    rows = await conn.fetch(
        """
        SELECT pid, application_name, client_addr::text AS client_addr,
               state,
               EXTRACT(EPOCH FROM (now() - xact_start))::int AS xact_age_s,
               left(query, 160) AS q
        FROM pg_stat_activity
        WHERE usename = $1
          AND pid <> pg_backend_pid()
          AND state IN ('active', 'idle in transaction', 'idle in transaction (aborted)')
          AND COALESCE(application_name, '') NOT LIKE '%alembic%'
          AND xact_start IS NOT NULL
        ORDER BY xact_start
        """,
        _APP_ROLE,
    )
    return [dict(r) for r in rows]


async def _drain(database_url: str, deadline_seconds: int) -> bool:
    """Poll until no non-alembic app txns remain or the deadline expires.

    Returns True if drained cleanly, False if the deadline expired. Either
    way the migration runs — the operator just gets visibility into who's
    still holding."""
    conn = await asyncpg.connect(_to_asyncpg_url(database_url))
    try:
        deadline = time.monotonic() + deadline_seconds
        last_count = -1
        while True:
            open_txns = await _open_app_txns(conn)
            if not open_txns:
                _log("drain: 0 in-flight app transactions")
                return True
            if time.monotonic() >= deadline:
                _log(
                    f"drain: timeout ({deadline_seconds}s) with "
                    f"{len(open_txns)} open; proceeding anyway"
                )
                for t in open_txns[:5]:
                    _log(
                        f"  - pid={t['pid']} addr={t['client_addr']} "
                        f"state={t['state']} age={t['xact_age_s']}s "
                        f"q={t['q']!r}"
                    )
                return False
            # Only log on count change to keep output readable.
            if len(open_txns) != last_count:
                _log(f"drain: {len(open_txns)} in-flight app txn(s) remain")
                last_count = len(open_txns)
            await asyncio.sleep(2)
    finally:
        await conn.close()


def _set_hold(redis_url: str, key: str) -> bool:
    """Best-effort: returns True if the hold flag was set."""
    try:
        r = redis.from_url(redis_url, socket_timeout=5)
        r.set(key, "1")
        _log(f"hold switch set ({key}=1)")
        return True
    except Exception as e:
        # Hold-switch failure is not fatal — the migration can still run,
        # but workers won't auto-pause. Surface the warning loudly.
        _log(f"WARNING: hold switch set failed: {e!r} — workers NOT paused")
        return False


def _clear_hold(redis_url: str, key: str) -> None:
    """Best-effort cleanup. Failure here is logged but never raised so we
    don't mask the underlying migration outcome."""
    with suppress(Exception):
        r = redis.from_url(redis_url, socket_timeout=5)
        r.delete(key)
        _log(f"hold switch cleared ({key})")


def _run_alembic(command: str) -> int:
    """Stream alembic output to our stdout and return its exit code."""
    _log(f"running: {command}")
    return subprocess.call(shlex.split(command))


async def _amain() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        _log("FATAL: DATABASE_URL is required")
        return 2

    redis_url = os.environ.get("REDIS_URL", "").strip()
    hold_key = os.environ.get("MIGRATE_HOLD_KEY", _DEFAULT_HOLD_KEY)
    drain_timeout = int(os.environ.get("MIGRATE_DRAIN_TIMEOUT", _DEFAULT_DRAIN_TIMEOUT))
    command = os.environ.get("MIGRATE_COMMAND", _DEFAULT_COMMAND)

    hold_set = False
    if redis_url:
        hold_set = _set_hold(redis_url, hold_key)
    else:
        _log("REDIS_URL not set; skipping hold switch")

    try:
        await _drain(database_url, drain_timeout)
        return _run_alembic(command)
    finally:
        if hold_set:
            _clear_hold(redis_url, hold_key)


def main() -> None:
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
