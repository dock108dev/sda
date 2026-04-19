"""Unit tests for Redis SET NX lock in trigger_flow_for_game.

Verifies that:
- Lock key uses flow:lock:{game_id} with 30-min TTL
- Second invocation for the same game_id exits cleanly without running pipeline
- Lock is released on task success
- Lock is NOT released on task failure (TTL is the safety net)
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Inject stubs so we can import the task module without a scraper venv.
# Must happen before any import of sports_scraper.*.
# ---------------------------------------------------------------------------

def _stub(name: str) -> MagicMock:
    m = MagicMock()
    sys.modules[name] = m
    return m


def _pkg(name: str) -> types.ModuleType:
    """Create a real package-type stub (needed for relative imports)."""
    m = types.ModuleType(name)
    m.__path__ = []          # marks it as a package
    m.__package__ = name
    sys.modules[name] = m
    return m


# Heavy third-party deps
for _dep in ["structlog", "celery", "celery.app", "sqlalchemy", "sqlalchemy.orm",
             "pydantic", "pydantic_settings", "redis", "httpx"]:
    sys.modules.setdefault(_dep, MagicMock())

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
_ss_utils = _stub("sports_scraper.utils")

# db_models.GameStatus.final.value must be a plain string so != comparisons work
_db_models_stub = sys.modules["sports_scraper.db.db_models"]
_db_models_stub.GameStatus.final.value = "final"

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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GAME_ID = 42
LOCK_KEY = f"flow:lock:{GAME_ID}"
LOCK_TIMEOUT_30MIN = 1800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_session_ctx(game_status: str = "final", has_pbp=True, has_artifacts=False, league_code="NBA"):
    """Return a context-manager mock that yields a configured DB session."""
    game = MagicMock()
    game.id = GAME_ID
    game.status = game_status  # plain string matches db_models.GameStatus.final.value = "final"
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

    # get_session and logger are module-level imports → patch on task module
    # acquire/release/start_job_run/complete_job_run are lazily imported inside
    # the function body → patch on their source modules in sys.modules
    redis_lock_mod = sys.modules["sports_scraper.utils.redis_lock"]
    job_runs_mod = sys.modules["sports_scraper.services.job_runs"]

    with (
        patch.object(_task_mod, "get_session", return_value=db_ctx),
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

    return result, m_acquire, m_release, m_pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFlowTriggerLock:
    def test_lock_key_and_ttl(self):
        """Lock must use flow:lock:{game_id} key and 30-min TTL."""
        _, m_acquire, _, _ = _run_task(lock_token="tok-abc")
        m_acquire.assert_called_once_with(LOCK_KEY, timeout=LOCK_TIMEOUT_30MIN)

    def test_second_invocation_skips_pipeline(self):
        """When lock is already held (acquire returns None), pipeline must not run."""
        result, _, m_release, m_pipeline = _run_task(lock_token=None)

        assert result == {"game_id": GAME_ID, "status": "skipped", "reason": "locked"}
        m_pipeline.assert_not_called()
        m_release.assert_not_called()

    def test_lock_released_on_success(self):
        """Lock must be released exactly once after a successful pipeline run."""
        _, _, m_release, _ = _run_task(lock_token="my-token")
        m_release.assert_called_once_with(LOCK_KEY, "my-token")

    def test_lock_not_released_on_failure(self):
        """Lock must NOT be released when pipeline raises — TTL is the safety net."""
        _, _, m_release, _ = _run_task(
            lock_token="my-token",
            pipeline_exc=RuntimeError("pipeline exploded"),
        )
        m_release.assert_not_called()
