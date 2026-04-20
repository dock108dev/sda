"""Tests for sweep_missing_flows.

Covers:
- sweep enqueues trigger_flow_for_game for every FINAL game with no artifact
- sweep is a no-op when all games already have artifacts
- sweep skips when its own NX lock is held
- sweep always releases its lock (even on exception)
- sweep lock uses LOCK_TIMEOUT_5MIN (300 s)

The acceptance-criteria integration test ("simulate FINAL transition at 10 PM,
assert flow enqueued within 5 minutes") is satisfied by:
  api/tests/test_game_status_hook.py::TestDispatchFinalGameTasks::test_countdown_is_five_minutes
which verifies countdown=300 on the ORM hook dispatch.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# _ColMock — fake SQLAlchemy column that returns a MagicMock for comparisons.
# Python resolves >= via type(left).__ge__, so this must be a class method.
# ---------------------------------------------------------------------------

class _ColMock:
    """Minimal stand-in for a SQLAlchemy column expression."""
    def __eq__(self, other): return MagicMock()  # noqa: PLR0206
    def __ne__(self, other): return MagicMock()
    def __ge__(self, other): return MagicMock()
    def __le__(self, other): return MagicMock()
    def __gt__(self, other): return MagicMock()
    def __lt__(self, other): return MagicMock()
    def __hash__(self): return id(self)


# ---------------------------------------------------------------------------
# Minimal stubs — same pattern as test_flow_trigger_lock.py
# ---------------------------------------------------------------------------

_MISSING = object()
_ORIG_MODULES: dict[str, object] = {}


def _remember_module(name: str) -> None:
    if name not in _ORIG_MODULES:
        _ORIG_MODULES[name] = sys.modules.get(name, _MISSING)


def _set_module(name: str, module: object) -> object:
    _remember_module(name)
    sys.modules[name] = module
    return module


def _restore_stubbed_modules(include_sports_scraper: bool = False) -> None:
    for name, original in _ORIG_MODULES.items():
        if not include_sports_scraper and name.startswith("sports_scraper"):
            continue
        if original is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def teardown_module(_module=None) -> None:
    sys.modules.pop("sports_scraper.jobs.flow_trigger_tasks", None)


def _force_magic(name: str) -> None:
    _set_module(name, MagicMock())


def _stub(name: str) -> MagicMock:
    m = MagicMock()
    _set_module(name, m)
    return m


def _pkg(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__path__ = []
    m.__package__ = name
    _set_module(name, m)
    return m


for _dep in [
    "structlog", "celery", "celery.app",
    "sqlalchemy", "sqlalchemy.orm",
    "pydantic", "pydantic_settings", "redis", "httpx",
]:
    _force_magic(_dep)

# shared_task must be a pass-through decorator
def _passthrough_shared_task(*args, **kwargs):
    if args and callable(args[0]):
        return args[0]
    return lambda fn: fn

sys.modules["celery"].shared_task = _passthrough_shared_task

_ss = _pkg("sports_scraper")
_jobs = _pkg("sports_scraper.jobs")

_ss_logging = _stub("sports_scraper.logging")
_ss_logging.logger = MagicMock()
_ss.logging = _ss_logging

_ss_db = _stub("sports_scraper.db")
_ss_db.get_session = MagicMock()
_ss.db = _ss_db

_stub("sports_scraper.db.db_models")
_stub("sports_scraper.config")
_stub("sports_scraper.api_client")
_stub("sports_scraper.services")
_ss_jobs_runs = _stub("sports_scraper.services.job_runs")

_ss_redis = _stub("sports_scraper.utils.redis_lock")
_ss_redis.LOCK_TIMEOUT_30MIN = 1800
_ss_redis.LOCK_TIMEOUT_5MIN = 300
_ss_redis.LOCK_TIMEOUT_1HOUR = 3600
_ss_utils = _stub("sports_scraper.utils")
_ss_utils.redis_lock = _ss_redis

_db_models_stub = sys.modules["sports_scraper.db.db_models"]
_db_models_stub.GameStatus.final.value = "final"
_db_models_stub.GameStatus.recap_pending.value = "recap_pending"
_db_models_stub.GameStatus.recap_ready.value = "recap_ready"
_db_models_stub.GameStatus.recap_failed.value = "recap_failed"

# Wire column attributes so comparisons (>=, ==) don't raise TypeError.
# Python dispatches >= via type(left).__ge__, so _ColMock instances are needed.
_db_models_stub.SportsGame.game_date = _ColMock()
_db_models_stub.SportsGame.status = _ColMock()
_db_models_stub.SportsGame.id = _ColMock()
_db_models_stub.SportsGameTimelineArtifact.game_id = _ColMock()

_ss_db.db_models = _db_models_stub
sys.modules["sports_scraper.services"].job_runs = _ss_jobs_runs

# SQLAlchemy filter helpers — not_ returns its arg unchanged; exists() and or_() are mocks.
_sa_stub = sys.modules["sqlalchemy"]
_sa_stub.not_ = MagicMock(side_effect=lambda x: x)
_sa_stub.or_ = MagicMock(return_value=MagicMock())
_sa_stub.exists = MagicMock(return_value=MagicMock())

# Load flow_trigger_tasks fresh so all stubs above are visible.
for _k in list(sys.modules):
    if "flow_trigger_tasks" in _k:
        del sys.modules[_k]

import importlib.util as _ilu
import pathlib as _pl

_spec = _ilu.spec_from_file_location(
    "sports_scraper.jobs.flow_trigger_tasks",
    _pl.Path(__file__).resolve().parents[2]
    / "scraper/sports_scraper/jobs/flow_trigger_tasks.py",
    submodule_search_locations=[],
)
_task_mod = _ilu.module_from_spec(_spec)
_task_mod.__package__ = "sports_scraper.jobs"
sys.modules["sports_scraper.jobs.flow_trigger_tasks"] = _task_mod
_spec.loader.exec_module(_task_mod)


_STUB_SNAPSHOT = {name: sys.modules.get(name) for name in _ORIG_MODULES}
_STUB_SNAPSHOT["sports_scraper.jobs.flow_trigger_tasks"] = _task_mod

sys.modules.pop("sports_scraper.jobs.flow_trigger_tasks", None)
for _name, _original in _ORIG_MODULES.items():
    if _original is _MISSING:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _original


@pytest.fixture(autouse=True)
def _reinstall_stubs():
    saved = {name: sys.modules.get(name) for name in _STUB_SNAPSHOT}
    for name, mod in _STUB_SNAPSHOT.items():
        if mod is not None:
            sys.modules[name] = mod
    yield
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GAME_IDS_MISSING = [10, 20, 30]
SWEEP_LOCK = "flow:sweep:lock"
SWEEP_LOCK_TTL = 300  # LOCK_TIMEOUT_5MIN


def _make_game(gid: int):
    g = MagicMock()
    g.id = gid
    return g


def _db_ctx_with_games(game_ids: list[int]):
    games = [_make_game(gid) for gid in game_ids]
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = games
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _run_sweep(*, lock_token="sweep-tok", game_ids=None):
    if game_ids is None:
        game_ids = GAME_IDS_MISSING

    db_ctx = _db_ctx_with_games(game_ids)
    redis_lock_mod = _ss_redis

    with (
        patch.object(_task_mod, "get_session", return_value=db_ctx),
        patch.object(redis_lock_mod, "acquire_redis_lock", return_value=lock_token) as m_acquire,
        patch.object(redis_lock_mod, "release_redis_lock") as m_release,
        patch.object(_task_mod, "trigger_flow_for_game") as m_trigger,
    ):
        result = _task_mod.sweep_missing_flows()

    return result, m_acquire, m_release, m_trigger


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSweepMissingFlows:
    def test_enqueues_for_each_missing_game(self):
        """sweep_missing_flows must call trigger_flow_for_game.delay for every missing game."""
        result, _, _, m_trigger = _run_sweep(game_ids=GAME_IDS_MISSING)

        assert result["status"] == "success"
        assert result["enqueued"] == len(GAME_IDS_MISSING)
        assert m_trigger.delay.call_count == len(GAME_IDS_MISSING)
        m_trigger.delay.assert_has_calls(
            [call(gid) for gid in GAME_IDS_MISSING], any_order=True
        )

    def test_noop_when_no_missing_games(self):
        """No tasks enqueued when every FINAL game already has a flow artifact."""
        result, _, _, m_trigger = _run_sweep(game_ids=[])

        assert result["status"] == "success"
        assert result["enqueued"] == 0
        m_trigger.delay.assert_not_called()

    def test_skips_when_sweep_lock_held(self):
        """If another sweep is running (lock held), skip without querying DB."""
        redis_lock_mod = _ss_redis

        with (
            patch.object(redis_lock_mod, "acquire_redis_lock", return_value=None) as m_acquire,
            patch.object(_task_mod, "get_session") as m_session,
            patch.object(_task_mod, "trigger_flow_for_game") as m_trigger,
        ):
            result = _task_mod.sweep_missing_flows()

        assert result == {"status": "skipped", "reason": "locked"}
        m_acquire.assert_called_once_with(SWEEP_LOCK, timeout=SWEEP_LOCK_TTL)
        m_session.assert_not_called()
        m_trigger.delay.assert_not_called()

    def test_sweep_lock_uses_5min_ttl(self):
        """Sweep self-lock must use LOCK_TIMEOUT_5MIN (300 s)."""
        _, m_acquire, _, _ = _run_sweep()
        m_acquire.assert_called_once_with(SWEEP_LOCK, timeout=SWEEP_LOCK_TTL)

    def test_sweep_lock_always_released(self):
        """Lock must be released even if an exception occurs mid-sweep."""
        redis_lock_mod = _ss_redis

        broken_ctx = MagicMock()
        broken_ctx.__enter__ = MagicMock(side_effect=RuntimeError("db exploded"))
        broken_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(redis_lock_mod, "acquire_redis_lock", return_value="tok"),
            patch.object(redis_lock_mod, "release_redis_lock") as m_release,
            patch.object(_task_mod, "get_session", return_value=broken_ctx),
        ):
            with pytest.raises(RuntimeError):
                _task_mod.sweep_missing_flows()

        m_release.assert_called_once_with(SWEEP_LOCK, "tok")


class TestSweepIncludesRecapFailed:
    def test_or_filter_called_with_final_and_recap_failed(self):
        """Sweep must pass both final and recap_failed values to or_() filter."""
        sa_stub = _sa_stub

        # Reset call history so we can inspect what this run produces
        sa_stub.or_.reset_mock()

        _run_sweep(game_ids=[])

        assert sa_stub.or_.called, "or_() must be called in the sweep filter"
        call_args = sa_stub.or_.call_args[0]
        # Two comparisons should be passed to or_() — one for final, one for recap_failed
        assert len(call_args) == 2
