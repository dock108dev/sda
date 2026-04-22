"""Pool lifecycle state machine — named guards and audit log.

States: draft → open → locked → live → final

Valid transitions (action name → target state):
  open_pool  (draft  → open)   guards: tournament_id set, entry_deadline set
  lock_pool  (open   → locked) guards: at least 1 entry
  go_live    (locked → live)   guards: state check only; also enables scoring
  finalize   (live   → final)  guards: state check only
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.audit as audit
from app.db.golf import GolfTournamentField
from app.db.golf_pools import GolfPool, GolfPoolEntry, PoolLifecycleEvent


class PoolStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    LOCKED = "locked"
    LIVE = "live"
    FINAL = "final"


_VALID_TRANSITIONS: frozenset[tuple[PoolStatus, PoolStatus]] = frozenset({
    (PoolStatus.DRAFT, PoolStatus.OPEN),
    (PoolStatus.OPEN, PoolStatus.LOCKED),
    (PoolStatus.LOCKED, PoolStatus.LIVE),
    (PoolStatus.LIVE, PoolStatus.FINAL),
})

# Maps the URL action name to the target PoolStatus.
ACTION_MAP: dict[str, PoolStatus] = {
    "open": PoolStatus.OPEN,
    "lock": PoolStatus.LOCKED,
    "go_live": PoolStatus.LIVE,
    "finalize": PoolStatus.FINAL,
}


class TransitionError(Exception):
    """Raised when a pool state transition is not permitted or a guard fails."""

    def __init__(
        self,
        from_status: PoolStatus,
        to_status: PoolStatus,
        reason: str | None = None,
    ) -> None:
        self.from_status = from_status
        self.to_status = to_status
        self.reason = reason
        msg = f"Cannot transition pool from '{from_status.value}' to '{to_status.value}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class PoolStateMachine:
    """Encapsulates all state transitions for a GolfPool.

    Each named method asserts the current state allows the transition, runs
    pre-condition guards, updates pool.status, and writes an audit row to
    pool_lifecycle_events.
    """

    def __init__(self, pool: GolfPool, db: AsyncSession) -> None:
        self._pool = pool
        self._db = db

    async def open_pool(
        self,
        actor_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """draft → open. Requires: tournament_id set, entry_deadline set."""
        pool = self._pool
        from_status = PoolStatus(pool.status)
        to_status = PoolStatus.OPEN
        self._assert_valid(from_status, to_status)
        if pool.tournament_id is None:
            raise TransitionError(from_status, to_status, "tournament_id must be set before opening")
        if pool.entry_deadline is None:
            raise TransitionError(from_status, to_status, "entry_deadline must be set before opening")
        field_result = await self._db.execute(
            select(func.count(GolfTournamentField.dg_id)).where(
                GolfTournamentField.tournament_id == pool.tournament_id
            )
        )
        if (field_result.scalar() or 0) == 0:
            raise TransitionError(
                from_status, to_status,
                "tournament field data is not available (field_available: false)",
            )
        await self._apply(from_status, to_status, actor_user_id, metadata)

    async def lock_pool(
        self,
        actor_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """open → locked. Requires: at least 1 entry."""
        pool = self._pool
        from_status = PoolStatus(pool.status)
        to_status = PoolStatus.LOCKED
        self._assert_valid(from_status, to_status)
        result = await self._db.execute(
            select(func.count(GolfPoolEntry.id)).where(GolfPoolEntry.pool_id == pool.id)
        )
        entry_count = result.scalar() or 0
        if entry_count < 1:
            raise TransitionError(from_status, to_status, "pool must have at least 1 entry before locking")
        await self._apply(from_status, to_status, actor_user_id, metadata)

    async def go_live(
        self,
        actor_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """locked → live. Also enables scoring."""
        from_status = PoolStatus(self._pool.status)
        to_status = PoolStatus.LIVE
        self._assert_valid(from_status, to_status)
        self._pool.scoring_enabled = True
        await self._apply(from_status, to_status, actor_user_id, metadata)

    async def finalize(
        self,
        actor_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """live → final."""
        from_status = PoolStatus(self._pool.status)
        to_status = PoolStatus.FINAL
        self._assert_valid(from_status, to_status)
        await self._apply(from_status, to_status, actor_user_id, metadata)

    async def transition(
        self,
        action: str,
        actor_user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Dispatch a named action to the appropriate transition method.

        Valid actions: open, lock, go_live, finalize.
        """
        dispatch: dict[str, Any] = {
            "open": self.open_pool,
            "lock": self.lock_pool,
            "go_live": self.go_live,
            "finalize": self.finalize,
        }
        if action not in dispatch:
            raise ValueError(f"Unknown action {action!r}. Valid actions: {sorted(dispatch)}")
        await dispatch[action](actor_user_id=actor_user_id, metadata=metadata)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_valid(self, from_status: PoolStatus, to_status: PoolStatus) -> None:
        if (from_status, to_status) not in _VALID_TRANSITIONS:
            raise TransitionError(from_status, to_status)

    async def _apply(
        self,
        from_status: PoolStatus,
        to_status: PoolStatus,
        actor_user_id: int | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._pool.status = to_status.value
        self._db.add(
            PoolLifecycleEvent(
                pool_id=self._pool.id,
                from_state=from_status.value,
                to_state=to_status.value,
                actor_user_id=actor_user_id,
                event_metadata=metadata,
            )
        )
        await self._db.flush()
        audit.emit(
            "pool_state_transition",
            actor_type="user" if actor_user_id is not None else "system",
            actor_id=str(actor_user_id) if actor_user_id is not None else None,
            club_id=self._pool.club_id,
            resource_type="pool",
            resource_id=str(self._pool.id),
            payload={
                "from_state": from_status.value,
                "to_state": to_status.value,
                **(metadata or {}),
            },
        )
