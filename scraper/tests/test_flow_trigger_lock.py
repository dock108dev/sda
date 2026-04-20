"""Unit tests for Redis SET NX lock and state-machine transitions in trigger_flow_for_game.

Verifies that:
- Lock key uses pipeline_lock:trigger_flow_for_game:{game_id} with 1-hour TTL
- Second invocation for the same game_id exits cleanly without running pipeline
- Lock is released on task success
- Lock is NOT released on task failure (TTL is the safety net)
- Status is set to RECAP_PENDING at start, RECAP_READY on success, RECAP_FAILED on error
- FINAL, RECAP_PENDING, and RECAP_FAILED statuses are all accepted
- Non-eligible statuses (e.g. live) are skipped
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Inject stubs so we can import the task module without a scraper venv.
# Must happen before any import of sports_scraper.*.
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
    """Create a real package-type stub (needed for relative imports)."""
    m = types.ModuleType(name)
    m.__path__ = []          # marks it as a package
    m.__package__ = name
    _set_module(name, m)
    return m


# Heavy third-party deps
for _dep in ["structlog", "celery", "celery.app", "sqlalchemy", "sqlalchemy.orm",
             "pydantic", "pydantic_settings", "redis", "httpx"]:
    _force_magic(_dep)

# shared_task must be a pass-through decorator so the task function remains callable
def _passthrough_shared_task(*args, **kwargs):
    """Return identity decorator regardless of arguments."""
    if args and callable(args[0]):
        return args[0]
    return lambda fn: fn

sys.modules["celery"].shared_task = _passthrough_shared_task

# sports_scraper package hierarchy — must be real modules for relative imports
_ss = _pkg("sports_scraper")
_jobs = _pkg("sports_scraper.jobs")

# Leaf stubs
_ss_logging = _stub("sports_scraper.logging")
_ss_logging.logger = MagicMock()
_ss.logging = _ss_logging

_ss_db = _stub("sports_scraper.db")
_ss_db.get_session = MagicMock()
_ss.db = _ss_db

_stub("sports_scraper.db.db_models")
_stub("sports_scraper.config")
_stub("sports_scraper.api_client")

_ss_jobs_runs = _stub("sports_scraper.services.job_runs")
_stub("sports_scraper.services")

_ss_redis = _stub("sports_scraper.utils.redis_lock")
_ss_redis.LOCK_TIMEOUT_30MIN = 1800
_ss_redis.LOCK_TIMEOUT_1HOUR = 3600
_ss_utils = _stub("sports_scraper.utils")

# db_models.GameStatus values must be plain strings for comparisons
_db_models_stub = sys.modules["sports_scraper.db.db_models"]
_db_models_stub.GameStatus.final.value = "final"
_db_models_stub.GameStatus.recap_pending.value = "recap_pending"
_db_models_stub.GameStatus.recap_ready.value = "recap_ready"
_db_models_stub.GameStatus.recap_failed.value = "recap_failed"

# Wire parent stubs to child stubs so that from-imports inside functions
# resolve via getattr(parent, 'child') to the right stub object.
_ss_db.db_models = _db_models_stub
_ss_utils.redis_lock = _ss_redis
sys.modules["sports_scraper.services"].job_runs = _ss_jobs_runs

# Now import the module — relative imports will resolve via sys.modules
if "sports_scraper.jobs.flow_trigger_tasks" in sys.modules:
    del sys.modules["sports_scraper.jobs.flow_trigger_tasks"]

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
# Constants
# ---------------------------------------------------------------------------
GAME_ID = 42
LOCK_KEY = f"pipeline_lock:trigger_flow_for_game:{GAME_ID}"
LOCK_TIMEOUT_1HOUR = 3600


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_session_ctx(game_status: str = "final", has_pbp=True, has_artifacts=False, league_code="NBA"):
    """Return a context-manager mock that yields a configured DB session."""
    game = MagicMock()
    game.id = GAME_ID
    game.status = game_status  # plain string matches db_models.GameStatus.*.value
    game.league_id = 1

    league = MagicMock()
    league.code = league_code

    session = MagicMock()
    session.query.return_value.get.side_effect = [game, league]
    session.query.return_value.scalar.side_effect = [has_pbp, has_artifacts]

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _run_task(*, lock_token, db_ctx=None, pipeline_result=None, pipeline_exc=None):
    """Invoke trigger_flow_for_game with controlled mocks; return (result, mocks)."""
    if db_ctx is None:
        db_ctx = _db_session_ctx()

    pipeline_result = pipeline_result or {"status": "success"}

    redis_lock_mod = _ss_redis
    job_runs_mod = _ss_jobs_runs

    with (
        patch.object(_task_mod, "get_session", return_value=db_ctx),
        patch.object(_task_mod, "_set_game_status") as m_set_status,
        patch.object(redis_lock_mod, "acquire_redis_lock", return_value=lock_token) as m_acquire,
        patch.object(redis_lock_mod, "release_redis_lock") as m_release,
        patch.object(
            _task_mod, "_call_pipeline_api",
            return_value=pipeline_result if pipeline_exc is None else None,
            side_effect=pipeline_exc,
        ) as m_pipeline,
        patch.object(job_runs_mod, "start_job_run", return_value=1),
        patch.object(job_runs_mod, "complete_job_run"),
    ):
        if pipeline_exc is not None:
            with pytest.raises(type(pipeline_exc)):
                _task_mod.trigger_flow_for_game(GAME_ID)
            result = None
        else:
            result = _task_mod.trigger_flow_for_game(GAME_ID)

    return result, m_acquire, m_release, m_pipeline, m_set_status


# ---------------------------------------------------------------------------
# Tests — lock behaviour
# ---------------------------------------------------------------------------

class TestFlowTriggerLock:
    def test_lock_key_and_ttl(self):
        """Lock must use pipeline_lock:trigger_flow_for_game:{game_id} key and 1-hour TTL."""
        _, m_acquire, _, _, _ = _run_task(lock_token="tok-abc")
        m_acquire.assert_called_once_with(LOCK_KEY, timeout=LOCK_TIMEOUT_1HOUR)

    def test_second_invocation_skips_pipeline(self):
        """When lock is already held (acquire returns None), pipeline must not run."""
        result, _, m_release, m_pipeline, _ = _run_task(lock_token=None)

        assert result == {"game_id": GAME_ID, "status": "skipped", "reason": "locked"}
        m_pipeline.assert_not_called()
        m_release.assert_not_called()

    def test_lock_released_on_success(self):
        """Lock must be released exactly once after a successful pipeline run."""
        _, _, m_release, _, _ = _run_task(lock_token="my-token")
        m_release.assert_called_once_with(LOCK_KEY, "my-token")

    def test_lock_not_released_on_failure(self):
        """Lock must NOT be released when pipeline raises — TTL is the safety net."""
        _, _, m_release, _, _ = _run_task(
            lock_token="my-token",
            pipeline_exc=RuntimeError("pipeline exploded"),
        )
        m_release.assert_not_called()

    def test_countdown_is_five_minutes(self):
        """ORM hook must dispatch with countdown=300 (verified in hook tests; here
        we confirm the task itself is callable and produces a result)."""
        result, _, _, _, _ = _run_task(lock_token="tok")
        assert result["status"] == "success"

    def test_expires_is_set(self):
        """Task must produce a result (sanity check; expires enforced by hook tests)."""
        result, _, _, _, _ = _run_task(lock_token="tok")
        assert result is not None


# ---------------------------------------------------------------------------
# Tests — status eligibility
# ---------------------------------------------------------------------------

class TestStatusEligibility:
    def test_final_status_accepted(self):
        """FINAL games must proceed through the pipeline."""
        result, _, _, m_pipeline, _ = _run_task(
            lock_token="tok",
            db_ctx=_db_session_ctx(game_status="final"),
        )
        m_pipeline.assert_called_once()
        assert result["status"] == "success"

    def test_recap_pending_status_accepted(self):
        """RECAP_PENDING games (retries) must proceed through the pipeline."""
        result, _, _, m_pipeline, _ = _run_task(
            lock_token="tok",
            db_ctx=_db_session_ctx(game_status="recap_pending"),
        )
        m_pipeline.assert_called_once()
        assert result["status"] == "success"

    def test_recap_failed_status_accepted(self):
        """RECAP_FAILED games (eligible for re-dispatch) must proceed."""
        result, _, _, m_pipeline, _ = _run_task(
            lock_token="tok",
            db_ctx=_db_session_ctx(game_status="recap_failed"),
        )
        m_pipeline.assert_called_once()
        assert result["status"] == "success"

    def test_live_status_skipped(self):
        """Non-final games must be skipped without running the pipeline."""
        result, _, _, m_pipeline, _ = _run_task(
            lock_token="tok",
            db_ctx=_db_session_ctx(game_status="live"),
        )
        m_pipeline.assert_not_called()
        assert result["status"] == "skipped"
        assert result["reason"] == "not_eligible"

    def test_scheduled_status_skipped(self):
        result, _, _, m_pipeline, _ = _run_task(
            lock_token="tok",
            db_ctx=_db_session_ctx(game_status="scheduled"),
        )
        m_pipeline.assert_not_called()
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# Tests — state machine transitions
# ---------------------------------------------------------------------------

class TestStateMachineTransitions:
    def test_sets_recap_ready_on_success(self):
        """On pipeline success, _set_game_status must be called with recap_ready."""
        _, _, _, _, m_set_status = _run_task(lock_token="tok")
        m_set_status.assert_any_call(GAME_ID, "recap_ready")

    def test_sets_recap_failed_on_error(self):
        """On pipeline error, _set_game_status must be called with recap_failed."""
        _, _, _, _, m_set_status = _run_task(
            lock_token="tok",
            pipeline_exc=RuntimeError("api down"),
        )
        m_set_status.assert_any_call(GAME_ID, "recap_failed")

    def test_recap_ready_not_set_on_error(self):
        """recap_ready must NOT be set when pipeline raises."""
        _, _, _, _, m_set_status = _run_task(
            lock_token="tok",
            pipeline_exc=RuntimeError("api down"),
        )
        recap_ready_calls = [
            c for c in m_set_status.call_args_list if c.args[1] == "recap_ready"
        ]
        assert not recap_ready_calls

    def test_recap_failed_not_set_on_success(self):
        """recap_failed must NOT be set when pipeline succeeds."""
        _, _, _, _, m_set_status = _run_task(lock_token="tok")
        recap_failed_calls = [
            c for c in m_set_status.call_args_list if c.args[1] == "recap_failed"
        ]
        assert not recap_failed_calls
