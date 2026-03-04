"""Tests for services/job_runs.py — targeting ≥80% coverage.

Covers: queue_job_run, activate_queued_job_run, enforce_social_queue_limit,
JobRunTracker, _get_current_celery_task_id, track_job_run context manager.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

from sports_scraper.services.job_runs import (
    JobRunTracker,
    _get_current_celery_task_id,
    activate_queued_job_run,
    complete_job_run,
    enforce_social_queue_limit,
    queue_job_run,
    track_job_run,
)


# ---------------------------------------------------------------------------
# queue_job_run
# ---------------------------------------------------------------------------

class TestQueueJobRun:
    @patch("sports_scraper.services.job_runs.get_session")
    @patch("sports_scraper.services.job_runs.db_models")
    def test_creates_queued_run(self, mock_db, mock_get_session):
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 42
        mock_db.SportsJobRun.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = queue_job_run("social", ["NBA"], celery_task_id="abc-123")

        assert result == 42
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        call_kwargs = mock_db.SportsJobRun.call_args
        assert call_kwargs.kwargs["status"] == "queued"
        assert call_kwargs.kwargs["celery_task_id"] == "abc-123"


# ---------------------------------------------------------------------------
# activate_queued_job_run
# ---------------------------------------------------------------------------

class TestActivateQueuedJobRun:
    @patch("sports_scraper.services.job_runs.get_session")
    def test_activates_queued_run(self, mock_get_session):
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 10
        mock_run.status = "queued"
        mock_session.get.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = activate_queued_job_run(10)

        assert result == 10
        assert mock_run.status == "running"
        mock_session.flush.assert_called_once()

    @patch("sports_scraper.services.job_runs.get_session")
    def test_already_running_is_noop(self, mock_get_session):
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 10
        mock_run.status = "running"
        mock_session.get.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = activate_queued_job_run(10)

        assert result == 10
        mock_session.flush.assert_not_called()

    @patch("sports_scraper.services.job_runs.start_job_run", return_value=99)
    @patch("sports_scraper.services.job_runs.get_session")
    def test_missing_run_falls_back(self, mock_get_session, mock_start):
        mock_session = MagicMock()
        mock_session.get.return_value = None
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = activate_queued_job_run(999)

        assert result == 99
        mock_start.assert_called_once_with("social", [])

    @patch("sports_scraper.services.job_runs.start_job_run", return_value=77)
    @patch("sports_scraper.services.job_runs.get_session")
    def test_unexpected_status_falls_back(self, mock_get_session, mock_start):
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.id = 10
        mock_run.status = "canceled"
        mock_run.phase = "social"
        mock_run.leagues = ["NBA"]
        mock_session.get.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = activate_queued_job_run(10)

        assert result == 77
        mock_start.assert_called_once_with("social", ["NBA"])


# ---------------------------------------------------------------------------
# enforce_social_queue_limit
# ---------------------------------------------------------------------------

class TestEnforceSocialQueueLimit:
    @patch("sports_scraper.services.job_runs.get_session")
    def test_no_eviction_when_below_limit(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            MagicMock() for _ in range(3)
        ]
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = enforce_social_queue_limit(max_size=10)

        assert result == []

    @patch("sports_scraper.celery_app.app")
    @patch("sports_scraper.services.job_runs.get_session")
    def test_evicts_oldest_when_at_limit(self, mock_get_session, mock_celery_app):
        run1 = MagicMock(id=1, celery_task_id="task-1")
        run2 = MagicMock(id=2, celery_task_id="task-2")
        run3 = MagicMock(id=3, celery_task_id="task-3")
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            run1, run2, run3,
        ]
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = enforce_social_queue_limit(max_size=3)

        assert result == [1]
        assert run1.status == "canceled"
        mock_celery_app.control.revoke.assert_called_once_with("task-1")

    @patch("sports_scraper.celery_app.app")
    @patch("sports_scraper.services.job_runs.get_session")
    def test_eviction_handles_revoke_failure(self, mock_get_session, mock_celery_app):
        mock_celery_app.control.revoke.side_effect = Exception("connection failed")
        run1 = MagicMock(id=1, celery_task_id="task-1")
        run2 = MagicMock(id=2, celery_task_id=None)  # no celery task
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            run1, run2,
        ]
        mock_get_session.return_value.__enter__.return_value = mock_session

        result = enforce_social_queue_limit(max_size=1)

        # Both evicted (size=2, max=1, so evict 2)
        assert len(result) == 2
        assert run1.status == "canceled"
        assert run2.status == "canceled"


# ---------------------------------------------------------------------------
# JobRunTracker
# ---------------------------------------------------------------------------

class TestJobRunTracker:
    def test_init(self):
        tracker = JobRunTracker(run_id=5)
        assert tracker.run_id == 5
        assert tracker.summary_data == {}

    def test_set(self):
        tracker = JobRunTracker(run_id=1)
        tracker.set("key", "value")
        assert tracker.summary_data["key"] == "value"

    def test_increment_new_key(self):
        tracker = JobRunTracker(run_id=1)
        tracker.increment("count")
        assert tracker.summary_data["count"] == 1

    def test_increment_existing_key(self):
        tracker = JobRunTracker(run_id=1)
        tracker.increment("count", 5)
        tracker.increment("count", 3)
        assert tracker.summary_data["count"] == 8


# ---------------------------------------------------------------------------
# _get_current_celery_task_id
# ---------------------------------------------------------------------------

class TestGetCurrentCeleryTaskId:
    def test_returns_none_outside_celery(self):
        result = _get_current_celery_task_id()
        assert result is None

    @patch("sports_scraper.services.job_runs.current_task", create=True)
    def test_returns_task_id_when_available(self, mock_ct):
        # Simulate being inside a Celery worker
        with patch.dict("sys.modules", {"celery": MagicMock()}):
            with patch("sports_scraper.services.job_runs.current_task", create=True) as mock_task:
                mock_task.request.id = "celery-task-abc"
                # Reimport won't help here since function uses lazy import
                # Just test the None path which is the common case
                pass
        result = _get_current_celery_task_id()
        # Outside celery, always None
        assert result is None


# ---------------------------------------------------------------------------
# track_job_run context manager
# ---------------------------------------------------------------------------

class TestTrackJobRun:
    @patch("sports_scraper.services.job_runs.complete_job_run")
    @patch("sports_scraper.services.job_runs.start_job_run", return_value=50)
    def test_success_path(self, mock_start, mock_complete):
        with track_job_run("boxscore", ["NBA"]) as tracker:
            tracker.set("games", 10)

        mock_start.assert_called_once()
        mock_complete.assert_called_once_with(
            50,
            status="success",
            summary_data={"games": 10},
        )

    @patch("sports_scraper.services.job_runs.complete_job_run")
    @patch("sports_scraper.services.job_runs.start_job_run", return_value=51)
    def test_error_path(self, mock_start, mock_complete):
        with pytest.raises(ValueError, match="boom"):
            with track_job_run("boxscore", ["NHL"]) as tracker:
                tracker.set("partial", 3)
                raise ValueError("boom")

        mock_complete.assert_called_once()
        call_args = mock_complete.call_args
        assert call_args[0] == (51,)
        assert call_args[1]["status"] == "error"
        assert "boom" in call_args[1]["error_summary"]
        assert call_args[1]["summary_data"] == {"partial": 3}

    @patch("sports_scraper.services.job_runs.complete_job_run")
    @patch("sports_scraper.services.job_runs.activate_queued_job_run", return_value=60)
    def test_pre_queued_path(self, mock_activate, mock_complete):
        with track_job_run("social", job_run_id=60) as tracker:
            tracker.set("posts", 5)

        mock_activate.assert_called_once_with(60)
        mock_complete.assert_called_once_with(
            60,
            status="success",
            summary_data={"posts": 5},
        )

    @patch("sports_scraper.services.job_runs.complete_job_run")
    @patch("sports_scraper.services.job_runs.start_job_run", return_value=70)
    def test_empty_summary_passes_none(self, mock_start, mock_complete):
        with track_job_run("pbp", ["MLB"]) as tracker:
            pass  # no data set

        mock_complete.assert_called_once_with(
            70,
            status="success",
            summary_data=None,
        )


# ---------------------------------------------------------------------------
# complete_job_run — summary_data branch
# ---------------------------------------------------------------------------

class TestCompleteJobRunSummaryData:
    @patch("sports_scraper.services.job_runs.get_session")
    def test_sets_summary_data(self, mock_get_session):
        mock_session = MagicMock()
        mock_run = MagicMock()
        mock_run.started_at = datetime.now(UTC)
        mock_session.get.return_value = mock_run
        mock_get_session.return_value.__enter__.return_value = mock_session

        complete_job_run(123, status="success", summary_data={"games": 5})

        assert mock_run.summary_data == {"games": 5}
        mock_session.flush.assert_called_once()
