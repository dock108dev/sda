"""Shared pytest fixtures and configuration."""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the scraper package is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

# Ensure the API package is importable (needed by sports_scraper.db and
# modules like job_runs.py that import from ``app.*`` before ``..db``).
API_ROOT = REPO_ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Set required environment variables before any imports
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx client."""
    client = MagicMock()
    client.get.return_value = MagicMock(status_code=200, json=lambda: {}, text="")
    return client


@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create a temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir


@pytest.fixture
def sample_nhl_play():
    """Sample NHL play data for testing."""
    return {
        "eventId": 151,
        "periodDescriptor": {"number": 1, "periodType": "REG"},
        "timeInPeriod": "04:00",
        "timeRemaining": "16:00",
        "situationCode": "1551",
        "typeDescKey": "goal",
        "sortOrder": 67,
        "details": {
            "scoringPlayerId": 8480840,
            "eventOwnerTeamId": 25,
            "homeScore": 1,
            "awayScore": 0,
            "shotType": "snap",
        },
    }


@pytest.fixture
def sample_ncaab_play():
    """Sample NCAAB play data for testing."""
    return {
        "period": 1,
        "sequenceNumber": 10,
        "clock": "15:30",
        "playType": "JumpShot",
        "team": "Duke",
        "playerId": 12345,
        "player": "John Doe",
        "homeScore": 10,
        "awayScore": 8,
        "description": "Made 3-pointer",
    }


@pytest.fixture
def sample_nba_play():
    """Sample NBA play data for testing."""
    return {
        "actionNumber": 5,
        "period": 1,
        "clock": "PT11M22.00S",
        "actionType": "2pt",
        "subType": "Layup",
        "description": "J. Tatum Layup",
        "scoreHome": "2",
        "scoreAway": "0",
        "teamTricode": "BOS",
        "personId": 1628369,
    }


# ---------------------------------------------------------------------------
# Golden corpus pass-rate tracking (ISSUE-050)
#
# pytest_runtest_logreport accumulates pass/fail per fixture as TestPipeline-
# Execution and TestCoverageFields run.  TestPassRateGate (defined last in
# test_golden_corpus.py) calls golden_corpus_outcomes() to get the final tally
# and fails if the rate is below GOLDEN_PASS_THRESHOLD.
#
# pytest_sessionfinish writes the per-sport markdown table to
# $GITHUB_STEP_SUMMARY so it appears in the PR Checks UI.
# ---------------------------------------------------------------------------

_GOLDEN_PIPELINE_CLASSES = frozenset(["TestPipelineExecution", "TestCoverageFields"])

# fixture_id (e.g. "nba_standard_win") → set of short test names that failed
_fixture_failures: dict[str, set[str]] = defaultdict(set)
# all fixture_ids seen in pipeline tests (union across both test classes)
_fixture_seen: set[str] = set()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when != "call":
        return
    nodeid: str = report.nodeid
    if "test_golden_corpus" not in nodeid:
        return
    if not any(cls in nodeid for cls in _GOLDEN_PIPELINE_CLASSES):
        return
    m = re.search(r"\[([a-z]+_[a-z_]+)\]", nodeid)
    if not m:
        return
    fixture_id = m.group(1)  # e.g. "nba_standard_win"
    _fixture_seen.add(fixture_id)
    if report.failed:
        # Short name: "test_pipeline_runs_without_error[nba_standard_win]"
        short = nodeid.rsplit("::", 1)[-1]
        _fixture_failures[fixture_id].add(short)


def _compute_golden_outcomes() -> dict:
    """Return pass/fail counts grouped by sport plus a list of failing fixtures."""
    sports = ["nba", "nhl", "mlb", "nfl", "ncaab"]
    rows: list[dict] = []
    total_passed = total_total = 0
    for sport in sports:
        sport_fixtures = {f for f in _fixture_seen if f.startswith(sport + "_")}
        sport_total = len(sport_fixtures)
        sport_failed = sum(1 for f in sport_fixtures if f in _fixture_failures)
        sport_passed = sport_total - sport_failed
        rows.append({
            "sport": sport.upper(),
            "passed": sport_passed,
            "failed": sport_failed,
            "total": sport_total,
        })
        total_passed += sport_passed
        total_total += sport_total
    return {
        "rows": rows,
        "total_passed": total_passed,
        "total_total": total_total,
        "failed_fixtures": {k: sorted(v) for k, v in _fixture_failures.items()},
    }


def _write_github_step_summary(outcomes: dict) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    threshold = int(os.environ.get("GOLDEN_PASS_THRESHOLD", "95"))
    total = outcomes["total_total"]
    passed = outcomes["total_passed"]
    rate = int(passed / total * 100) if total > 0 else 0
    status = "\u2705 PASS" if rate >= threshold else "\u274c FAIL"

    lines = [
        "## Golden Corpus Pipeline Gate",
        "",
        f"**Pass rate: {passed}/{total} ({rate}%)&nbsp;&nbsp;Threshold: {threshold}%&nbsp;&nbsp;{status}**",
        "",
        "| Sport | Passed | Failed | Total | Rate |",
        "|-------|--------|--------|-------|------|",
    ]
    for row in outcomes["rows"]:
        rt, rp = row["total"], row["passed"]
        sport_rate = int(rp / rt * 100) if rt > 0 else 0
        lines.append(f"| {row['sport']} | {rp} | {row['failed']} | {rt} | {sport_rate}% |")
    lines.append(
        f"| **Total** | **{passed}** | **{total - passed}** | **{total}** | **{rate}%** |"
    )

    failed = outcomes["failed_fixtures"]
    if failed:
        lines += ["", "### Failed Fixtures", ""]
        for fid, tests in sorted(failed.items()):
            test_names = ", ".join(t.split("[")[0] for t in tests)
            lines.append(f"- `{fid}`: {test_names}")

    with open(summary_path, "a") as fh:
        fh.write("\n".join(lines) + "\n")


def pytest_sessionfinish(session: pytest.Session, exitstatus: object) -> None:  # noqa: ARG001
    outcomes = _compute_golden_outcomes()
    if outcomes["total_total"] > 0:
        _write_github_step_summary(outcomes)


@pytest.fixture()
def golden_corpus_outcomes():
    """Returns the _compute_golden_outcomes callable.

    TestPassRateGate calls this after all pipeline tests have completed
    (file ordering ensures TestPassRateGate runs last).
    """
    return _compute_golden_outcomes
