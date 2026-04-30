"""Tests for game_status.compute_status_flags."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.sports import GameStatus
from app.services.game_status import FINAL_OR_POST_FINAL_STATUSES, compute_status_flags


@pytest.mark.parametrize(
    "status,expected_key,expected_val",
    [
        ("final", "is_final", True),
        ("completed", "is_final", True),
        ("official", "is_final", True),
        ("final", "is_truly_completed", True),
        ("completed", "is_truly_completed", True),
        ("official", "is_truly_completed", False),  # official != truly completed
        ("final", "read_eligible", True),
        ("live", "is_live", True),
        ("in_progress", "is_live", True),
        ("halftime", "is_live", True),
        ("scheduled", "is_pregame", True),
        ("pregame", "is_pregame", True),
        ("pre_game", "is_pregame", True),
        ("created", "is_pregame", True),
    ],
)
def test_status_flag(status: str, expected_key: str, expected_val: bool) -> None:
    flags = compute_status_flags(status)
    assert flags[expected_key] is expected_val


def test_none_status_all_false() -> None:
    flags = compute_status_flags(None)
    assert all(v is False for v in flags.values())


def test_unknown_status_all_false() -> None:
    flags = compute_status_flags("some_random_status")
    assert all(v is False for v in flags.values())


def test_case_insensitive() -> None:
    flags = compute_status_flags("FINAL")
    assert flags["is_final"] is True


def test_whitespace_handling() -> None:
    flags = compute_status_flags("  final  ")
    assert flags["is_final"] is True


def test_final_or_post_final_statuses_cover_recap_lifecycle() -> None:
    assert {
        "final",
        "completed",
        "official",
        "recap_pending",
        "recap_ready",
        "recap_failed",
        "archived",
    } == FINAL_OR_POST_FINAL_STATUSES
    assert GameStatus.final_or_post_final_values() == FINAL_OR_POST_FINAL_STATUSES


def test_scraper_status_duplicate_helper_is_absent() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "scraper/sports_scraper/utils/game_status.py").exists()


def test_mutual_exclusivity() -> None:
    """Live, final, pregame should be mutually exclusive for normal statuses."""
    for status in ["final", "live", "scheduled"]:
        flags = compute_status_flags(status)
        active = [k for k in ("is_live", "is_final", "is_pregame") if flags[k]]
        assert len(active) == 1, f"Status '{status}' has multiple active: {active}"
