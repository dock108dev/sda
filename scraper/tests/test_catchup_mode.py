from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_catchup_mode_schedules_only_five_minute_pbp_stats_refresh() -> None:
    scraper_dir = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(scraper_dir),
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
        "REDIS_URL": "redis://localhost:6379/2",
        "ENVIRONMENT": "development",
    }
    script = """
import json
from sports_scraper.celery_app import app
from sports_scraper.config import settings
payload = {
    "schedule": sorted(app.conf.beat_schedule.keys()),
    "task": app.conf.beat_schedule["catchup-pbp-stats-every-5m"]["task"],
    "schedule_args": app.conf.beat_schedule["catchup-pbp-stats-every-5m"].get("args"),
    "routes": sorted(app.conf.task_routes.keys()),
    "has_catchup_only_setting": hasattr(settings, "catchup_only"),
}
print("CELERY=" + json.dumps(payload))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=scraper_dir,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    celery_line = next(line for line in result.stdout.splitlines() if line.startswith("CELERY="))
    payload = json.loads(celery_line.removeprefix("CELERY="))

    assert payload == {
        "schedule": ["catchup-pbp-stats-every-5m"],
        "task": "poll_live_pbp",
        "schedule_args": None,
        "routes": ["poll_live_pbp"],
        "has_catchup_only_setting": False,
    }
