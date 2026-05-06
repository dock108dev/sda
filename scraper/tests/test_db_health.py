"""Unit tests for the pg.idle_in_txn observable-gauge plumbing."""

from __future__ import annotations

import pytest

from sports_scraper import db_health


@pytest.fixture(autouse=True)
def _reset_state():
    db_health.reset_state()
    yield
    db_health.reset_state()


def test_update_then_observe_returns_attributed_value() -> None:
    db_health.update_max_idle_in_txn_age("dock108", 42)
    db_health.update_max_idle_in_txn_age("readonly_user", 0)

    observations = {o.attributes["usename"]: o.value for o in db_health.collect_observations_for_test()}

    assert observations == {"dock108": 42, "readonly_user": 0}


def test_update_clamps_negative_to_zero() -> None:
    """A clock skew between Postgres and the scraper could in theory return
    a negative age; the gauge must never report a negative duration."""
    db_health.update_max_idle_in_txn_age("dock108", -5)

    observations = list(db_health.collect_observations_for_test())
    assert len(observations) == 1
    assert observations[0].value == 0


def test_repeated_update_overwrites_previous_value() -> None:
    db_health.update_max_idle_in_txn_age("dock108", 100)
    db_health.update_max_idle_in_txn_age("dock108", 5)

    observations = list(db_health.collect_observations_for_test())
    assert [o.value for o in observations] == [5]


def test_init_is_idempotent() -> None:
    """``init()`` may be called from worker boot and from each beat tick;
    repeated calls must not re-register the gauge or raise."""
    db_health.init()
    db_health.init()
    db_health.init()
    # No assertion needed — the test passes if no exception is raised.
