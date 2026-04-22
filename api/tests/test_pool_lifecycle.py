"""Unit tests for PoolStateMachine — 100% branch coverage required (DESIGN.md).

Tests exercise every valid transition, every invalid transition, and every
guard condition. No real DB is used; a lightweight async stub stands in.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.db.golf_pools import GolfPool, PoolLifecycleEvent
from app.services.pool_lifecycle import (
    ACTION_MAP,
    PoolStateMachine,
    PoolStatus,
    TransitionError,
    _VALID_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_result(scalar: Any = 0) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = scalar
    return r


class _StubDB:
    """Minimal async session stub.

    Returns scalar values in the order they are enqueued. open_pool consumes
    one value (field count); lock_pool consumes one value (entry count). Pass
    scalars positionally: _StubDB(field_or_entry_count, ...).
    """

    def __init__(self, *scalars: int) -> None:
        self._queue = list(scalars)
        self._idx = 0
        self.added: list[Any] = []
        self.flushed: bool = False

    async def execute(self, _stmt: Any) -> MagicMock:
        val = self._queue[self._idx] if self._idx < len(self._queue) else 0
        self._idx += 1
        return _make_result(val)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


def _make_pool(status: str = "draft", *, tournament_id: int | None = 1, entry_deadline: Any = "set") -> GolfPool:
    pool = GolfPool(
        code="TEST",
        name="Test Pool",
        club_code="club",
        status=status,
    )
    pool.id = 99
    pool.tournament_id = tournament_id
    pool.entry_deadline = datetime.now(timezone.utc) if entry_deadline == "set" else None
    pool.scoring_enabled = False
    return pool


# ---------------------------------------------------------------------------
# PoolStatus enum
# ---------------------------------------------------------------------------


class TestPoolStatus:
    def test_values(self) -> None:
        assert PoolStatus.DRAFT == "draft"
        assert PoolStatus.OPEN == "open"
        assert PoolStatus.LOCKED == "locked"
        assert PoolStatus.LIVE == "live"
        assert PoolStatus.FINAL == "final"

    def test_accepts_string(self) -> None:
        assert PoolStatus("open") is PoolStatus.OPEN


# ---------------------------------------------------------------------------
# TransitionError
# ---------------------------------------------------------------------------


class TestTransitionError:
    def test_message_without_reason(self) -> None:
        err = TransitionError(PoolStatus.DRAFT, PoolStatus.FINAL)
        assert "draft" in str(err)
        assert "final" in str(err)
        assert err.reason is None

    def test_message_with_reason(self) -> None:
        err = TransitionError(PoolStatus.DRAFT, PoolStatus.OPEN, "missing deadline")
        assert "missing deadline" in str(err)
        assert err.reason == "missing deadline"

    def test_attributes(self) -> None:
        err = TransitionError(PoolStatus.OPEN, PoolStatus.DRAFT)
        assert err.from_status == PoolStatus.OPEN
        assert err.to_status == PoolStatus.DRAFT

    def test_is_subclass_of_exception(self) -> None:
        with pytest.raises(Exception):
            raise TransitionError(PoolStatus.DRAFT, PoolStatus.FINAL)


# ---------------------------------------------------------------------------
# Valid transitions: transition graph is complete
# ---------------------------------------------------------------------------


class TestValidTransitionSet:
    def test_all_expected_transitions_present(self) -> None:
        expected = {
            (PoolStatus.DRAFT, PoolStatus.OPEN),
            (PoolStatus.OPEN, PoolStatus.LOCKED),
            (PoolStatus.LOCKED, PoolStatus.LIVE),
            (PoolStatus.LIVE, PoolStatus.FINAL),
        }
        assert expected == _VALID_TRANSITIONS

    def test_action_map_covers_all_transitions(self) -> None:
        assert set(ACTION_MAP) == {"open", "lock", "go_live", "finalize"}


# ---------------------------------------------------------------------------
# open_pool — draft → open
# ---------------------------------------------------------------------------


class TestOpenPool:
    def test_valid_transition_succeeds(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB(5)  # 5 field entries → field_available: true
        _run(PoolStateMachine(pool, db).open_pool())
        assert pool.status == "open"
        assert db.flushed

    def test_writes_audit_event(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB(5)
        _run(PoolStateMachine(pool, db).open_pool(actor_user_id=7))
        events = [o for o in db.added if isinstance(o, PoolLifecycleEvent)]
        assert len(events) == 1
        ev = events[0]
        assert ev.from_state == "draft"
        assert ev.to_state == "open"
        assert ev.actor_user_id == 7
        assert ev.pool_id == 99

    def test_writes_metadata(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB(5)
        _run(PoolStateMachine(pool, db).open_pool(metadata={"reason": "test"}))
        ev = [o for o in db.added if isinstance(o, PoolLifecycleEvent)][0]
        assert ev.event_metadata == {"reason": "test"}

    def test_guard_tournament_id_required(self) -> None:
        pool = _make_pool("draft", tournament_id=None)
        db = _StubDB()  # guard fires before DB query
        with pytest.raises(TransitionError) as exc_info:
            _run(PoolStateMachine(pool, db).open_pool())
        assert "tournament_id" in str(exc_info.value)
        assert pool.status == "draft"  # unchanged

    def test_guard_entry_deadline_required(self) -> None:
        pool = _make_pool("draft", entry_deadline=None)
        db = _StubDB()  # guard fires before DB query
        with pytest.raises(TransitionError) as exc_info:
            _run(PoolStateMachine(pool, db).open_pool())
        assert "entry_deadline" in str(exc_info.value)
        assert pool.status == "draft"

    def test_guard_field_not_available(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB(0)  # 0 field entries → field_available: false
        with pytest.raises(TransitionError) as exc_info:
            _run(PoolStateMachine(pool, db).open_pool())
        assert "field_available" in str(exc_info.value)
        assert pool.status == "draft"  # unchanged

    def test_guard_field_available_passes(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB(1)  # 1 field entry → field_available: true
        _run(PoolStateMachine(pool, db).open_pool())
        assert pool.status == "open"

    def test_invalid_from_open_raises(self) -> None:
        pool = _make_pool("open")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).open_pool())

    def test_invalid_from_locked_raises(self) -> None:
        pool = _make_pool("locked")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).open_pool())

    def test_invalid_from_live_raises(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).open_pool())

    def test_invalid_from_final_raises(self) -> None:
        pool = _make_pool("final")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).open_pool())


# ---------------------------------------------------------------------------
# lock_pool — open → locked
# ---------------------------------------------------------------------------


class TestLockPool:
    def test_valid_transition_succeeds(self) -> None:
        pool = _make_pool("open")
        db = _StubDB(3)
        _run(PoolStateMachine(pool, db).lock_pool())
        assert pool.status == "locked"
        assert db.flushed

    def test_writes_audit_event(self) -> None:
        pool = _make_pool("open")
        db = _StubDB(1)
        _run(PoolStateMachine(pool, db).lock_pool(actor_user_id=5))
        events = [o for o in db.added if isinstance(o, PoolLifecycleEvent)]
        assert len(events) == 1
        ev = events[0]
        assert ev.from_state == "open"
        assert ev.to_state == "locked"
        assert ev.actor_user_id == 5

    def test_guard_at_least_one_entry(self) -> None:
        pool = _make_pool("open")
        db = _StubDB(0)
        with pytest.raises(TransitionError) as exc_info:
            _run(PoolStateMachine(pool, db).lock_pool())
        assert "at least 1 entry" in str(exc_info.value)
        assert pool.status == "open"

    def test_invalid_from_draft_raises(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB()  # raises before DB query
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).lock_pool())

    def test_invalid_from_locked_raises(self) -> None:
        pool = _make_pool("locked")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).lock_pool())

    def test_invalid_from_live_raises(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).lock_pool())

    def test_invalid_from_final_raises(self) -> None:
        pool = _make_pool("final")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).lock_pool())


# ---------------------------------------------------------------------------
# go_live — locked → live
# ---------------------------------------------------------------------------


class TestGoLive:
    def test_valid_transition_succeeds(self) -> None:
        pool = _make_pool("locked")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).go_live())
        assert pool.status == "live"
        assert db.flushed

    def test_enables_scoring(self) -> None:
        pool = _make_pool("locked")
        pool.scoring_enabled = False
        db = _StubDB()
        _run(PoolStateMachine(pool, db).go_live())
        assert pool.scoring_enabled is True

    def test_writes_audit_event(self) -> None:
        pool = _make_pool("locked")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).go_live(actor_user_id=3))
        events = [o for o in db.added if isinstance(o, PoolLifecycleEvent)]
        assert len(events) == 1
        assert events[0].from_state == "locked"
        assert events[0].to_state == "live"
        assert events[0].actor_user_id == 3

    def test_invalid_from_draft_raises(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).go_live())

    def test_invalid_from_open_raises(self) -> None:
        pool = _make_pool("open")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).go_live())

    def test_invalid_from_live_raises(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).go_live())

    def test_invalid_from_final_raises(self) -> None:
        pool = _make_pool("final")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).go_live())


# ---------------------------------------------------------------------------
# finalize — live → final
# ---------------------------------------------------------------------------


class TestFinalize:
    def test_valid_transition_succeeds(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).finalize())
        assert pool.status == "final"
        assert db.flushed

    def test_writes_audit_event(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).finalize(actor_user_id=1, metadata={"note": "done"}))
        events = [o for o in db.added if isinstance(o, PoolLifecycleEvent)]
        assert len(events) == 1
        ev = events[0]
        assert ev.from_state == "live"
        assert ev.to_state == "final"
        assert ev.event_metadata == {"note": "done"}

    def test_invalid_from_draft_raises(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).finalize())

    def test_invalid_from_open_raises(self) -> None:
        pool = _make_pool("open")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).finalize())

    def test_invalid_from_locked_raises(self) -> None:
        pool = _make_pool("locked")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).finalize())

    def test_invalid_from_final_raises(self) -> None:
        pool = _make_pool("final")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).finalize())


# ---------------------------------------------------------------------------
# transition() dispatcher
# ---------------------------------------------------------------------------


class TestTransitionDispatcher:
    def test_open_action(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB(5)  # field count > 0
        _run(PoolStateMachine(pool, db).transition("open"))
        assert pool.status == "open"

    def test_lock_action(self) -> None:
        pool = _make_pool("open")
        db = _StubDB(2)
        _run(PoolStateMachine(pool, db).transition("lock"))
        assert pool.status == "locked"

    def test_go_live_action(self) -> None:
        pool = _make_pool("locked")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).transition("go_live"))
        assert pool.status == "live"

    def test_finalize_action(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).transition("finalize"))
        assert pool.status == "final"

    def test_unknown_action_raises_value_error(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB()
        with pytest.raises(ValueError, match="Unknown action"):
            _run(PoolStateMachine(pool, db).transition("invalid_action"))

    def test_invalid_state_for_action_raises_transition_error(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).transition("finalize"))

    def test_passes_actor_user_id_and_metadata(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).transition("finalize", actor_user_id=42, metadata={"k": "v"}))
        ev = [o for o in db.added if isinstance(o, PoolLifecycleEvent)][0]
        assert ev.actor_user_id == 42
        assert ev.event_metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# Audit row is always written exactly once per transition
# ---------------------------------------------------------------------------


class TestAuditRowWritten:
    @pytest.mark.parametrize(
        "status, action, scalar",
        [
            ("draft", "open", 5),   # scalar = field count (must be > 0)
            ("open", "lock", 1),    # scalar = entry count
            ("locked", "go_live", 0),
            ("live", "finalize", 0),
        ],
    )
    def test_exactly_one_audit_row_per_transition(
        self, status: str, action: str, scalar: int
    ) -> None:
        pool = _make_pool(status)
        db = _StubDB(scalar)
        _run(PoolStateMachine(pool, db).transition(action))
        lifecycle_events = [o for o in db.added if isinstance(o, PoolLifecycleEvent)]
        assert len(lifecycle_events) == 1

    def test_no_audit_row_on_failed_transition(self) -> None:
        pool = _make_pool("draft")
        db = _StubDB()
        with pytest.raises(TransitionError):
            _run(PoolStateMachine(pool, db).transition("finalize"))
        assert not db.added
        assert not db.flushed


# ---------------------------------------------------------------------------
# Null actor_user_id is allowed (system-initiated transitions)
# ---------------------------------------------------------------------------


class TestNullActorUserId:
    def test_actor_user_id_defaults_to_none(self) -> None:
        pool = _make_pool("live")
        db = _StubDB()
        _run(PoolStateMachine(pool, db).finalize())
        ev = [o for o in db.added if isinstance(o, PoolLifecycleEvent)][0]
        assert ev.actor_user_id is None
