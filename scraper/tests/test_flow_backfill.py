"""Tests for backfill_missing_flows.

Covers:
- Enqueues trigger_flow_for_game for every FINAL game missing a flow (7-day window)
- Uses staggered countdown (30 s * index) on apply_async
- No-op when all games already have flow artifacts
- Skips when backfill lock is already held
- Always releases its own lock (even on exception)
- Dry-run mode returns found/would_enqueue without calling apply_async
- Custom ``days`` parameter is forwarded to the DB query cutoff
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Stubs — same boilerplate as test_flow_sweep.py
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
    """Remove only the task module this file loaded; the autouse fixture's per-test
    teardown has already restored every other stub to pre-install state."""
    sys.modules.pop("sports_scraper.jobs.flow_trigger_tasks", None)


def _force_magic(name: str) -> None:
    _set_module(name, MagicMock())


class _ColMock:
    """Minimal stand-in for a SQLAlchemy column expression."""
    def __eq__(self, other): return MagicMock()  # noqa: PLR0206
    def __ne__(self, other): return MagicMock()
    def __ge__(self, other): return MagicMock()
    def __le__(self, other): return MagicMock()
    def __gt__(self, other): return MagicMock()
    def __lt__(self, other): return MagicMock()
    def __hash__(self): return id(self)


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
_ss_redis.LOCK_TIMEOUT_10MIN = 600
_ss_redis.LOCK_TIMEOUT_5MIN = 300
_ss_utils = _stub("sports_scraper.utils")
_ss_utils.redis_lock = _ss_redis

_db_models_stub = sys.modules["sports_scraper.db.db_models"]
_db_models_stub.GameStatus.final.value = "final"

_db_models_stub.SportsGame.game_date = _ColMock()
_db_models_stub.SportsGame.status = _ColMock()
_db_models_stub.SportsGame.id = _ColMock()
_db_models_stub.SportsGameTimelineArtifact.game_id = _ColMock()

_ss_db.db_models = _db_models_stub
sys.modules["sports_scraper.services"].job_runs = _ss_jobs_runs

_sa_stub = sys.modules["sqlalchemy"]
_sa_stub.not_ = MagicMock(side_effect=lambda x: x)
_sa_stub.exists = MagicMock(return_value=MagicMock())

# Load flow_trigger_tasks fresh
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


# Snapshot installed stubs BEFORE restoring originals, so the autouse fixture
# can re-install them for each test.
_STUB_SNAPSHOT = {name: sys.modules.get(name) for name in _ORIG_MODULES}
_STUB_SNAPSHOT["sports_scraper.jobs.flow_trigger_tasks"] = _task_mod

# Remove the dynamically-loaded task module and restore pre-stub state for every
# module we replaced, so sibling test files collected after us see real modules.
# If the original was _MISSING, pop the stub so a fresh import will reload the
# real module on demand; otherwise put the real module back. Restoring the real
# parent package preserves class identity for tests that already imported from it.
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

GAME_IDS = [101, 202, 303]
BACKFILL_LOCK = "flow:backfill:lock"
BACKFILL_LOCK_TTL = 600  # LOCK_TIMEOUT_10MIN
STAGGER = 30  # _BACKFILL_STAGGER_SECONDS


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


def _run_backfill(*, lock_token="backfill-tok", game_ids=None, dry_run=False, days=7):
    if game_ids is None:
        game_ids = GAME_IDS

    db_ctx = _db_ctx_with_games(game_ids)
    redis_lock_mod = _ss_redis

    with (
        patch.object(_task_mod, "get_session", return_value=db_ctx),
        patch.object(redis_lock_mod, "acquire_redis_lock", return_value=lock_token) as m_acquire,
        patch.object(redis_lock_mod, "release_redis_lock") as m_release,
        patch.object(_task_mod, "trigger_flow_for_game") as m_trigger,
    ):
        result = _task_mod.backfill_missing_flows(dry_run=dry_run, days=days)

    return result, m_acquire, m_release, m_trigger


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBackfillMissingFlows:
    def test_enqueues_for_each_missing_game(self):
        """backfill_missing_flows must call apply_async for every game missing a flow."""
        result, _, _, m_trigger = _run_backfill(game_ids=GAME_IDS)

        assert result["status"] == "success"
        assert result["found"] == len(GAME_IDS)
        assert result["enqueued"] == len(GAME_IDS)
        assert m_trigger.apply_async.call_count == len(GAME_IDS)

    def test_staggered_countdown(self):
        """Each game must be enqueued with countdown = index * 30."""
        _, _, _, m_trigger = _run_backfill(game_ids=GAME_IDS)

        expected_calls = [
            call(args=[gid], countdown=idx * STAGGER)
            for idx, gid in enumerate(GAME_IDS)
        ]
        m_trigger.apply_async.assert_has_calls(expected_calls, any_order=False)

    def test_noop_when_no_missing_games(self):
        """No tasks enqueued when all FINAL games already have flow artifacts."""
        result, _, _, m_trigger = _run_backfill(game_ids=[])

        assert result["status"] == "success"
        assert result["found"] == 0
        assert result["enqueued"] == 0
        m_trigger.apply_async.assert_not_called()

    def test_skips_when_lock_held(self):
        """If another backfill is running (lock held), return skipped immediately."""
        redis_lock_mod = _ss_redis

        with (
            patch.object(redis_lock_mod, "acquire_redis_lock", return_value=None) as m_acquire,
            patch.object(_task_mod, "get_session") as m_session,
            patch.object(_task_mod, "trigger_flow_for_game") as m_trigger,
        ):
            result = _task_mod.backfill_missing_flows()

        assert result == {"status": "skipped", "reason": "locked"}
        m_acquire.assert_called_once_with(BACKFILL_LOCK, timeout=BACKFILL_LOCK_TTL)
        m_session.assert_not_called()
        m_trigger.apply_async.assert_not_called()

    def test_lock_uses_10min_ttl(self):
        """Backfill self-lock must use LOCK_TIMEOUT_10MIN (600 s)."""
        _, m_acquire, _, _ = _run_backfill()
        m_acquire.assert_called_once_with(BACKFILL_LOCK, timeout=BACKFILL_LOCK_TTL)

    def test_lock_always_released(self):
        """Lock must be released even if an exception occurs mid-backfill."""
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
                _task_mod.backfill_missing_flows()

        m_release.assert_called_once_with(BACKFILL_LOCK, "tok")

    def test_dry_run_does_not_enqueue(self):
        """In dry-run mode, apply_async must not be called."""
        result, _, _, m_trigger = _run_backfill(game_ids=GAME_IDS, dry_run=True)

        assert result["status"] == "dry_run"
        assert result["found"] == len(GAME_IDS)
        assert result["would_enqueue"] == len(GAME_IDS)
        m_trigger.apply_async.assert_not_called()

    def test_dry_run_still_acquires_lock(self):
        """Dry-run mode still acquires the backfill lock to prevent concurrent dry-runs."""
        _, m_acquire, m_release, _ = _run_backfill(dry_run=True)
        m_acquire.assert_called_once_with(BACKFILL_LOCK, timeout=BACKFILL_LOCK_TTL)
        m_release.assert_called_once()

    def test_custom_days_parameter(self):
        """days parameter is accepted without error and result reflects found games."""
        result, _, _, m_trigger = _run_backfill(game_ids=[5, 6], days=3)

        assert result["status"] == "success"
        assert result["found"] == 2
        assert result["enqueued"] == 2
        assert m_trigger.apply_async.call_count == 2
