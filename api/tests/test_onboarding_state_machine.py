"""Unit tests for the onboarding session state machine.

100% branch coverage required per DESIGN.md.
"""

from __future__ import annotations

import pytest

from app.services.onboarding_state_machine import (
    InvalidTransitionError,
    SessionStatus,
    assert_can_transition,
    is_terminal,
)


# ---------------------------------------------------------------------------
# SessionStatus enum
# ---------------------------------------------------------------------------


class TestSessionStatus:
    def test_values(self) -> None:
        assert SessionStatus.PENDING == "pending"
        assert SessionStatus.PAID == "paid"
        assert SessionStatus.CLAIMED == "claimed"
        assert SessionStatus.EXPIRED == "expired"

    def test_accepts_string(self) -> None:
        assert SessionStatus("pending") is SessionStatus.PENDING


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------


class TestValidTransitions:
    @pytest.mark.parametrize(
        "from_s, to_s",
        [
            (SessionStatus.PENDING, SessionStatus.PAID),
            (SessionStatus.PAID, SessionStatus.CLAIMED),
            (SessionStatus.PENDING, SessionStatus.EXPIRED),
            (SessionStatus.PAID, SessionStatus.EXPIRED),
            (SessionStatus.CLAIMED, SessionStatus.EXPIRED),
        ],
    )
    def test_valid_transition_does_not_raise(
        self, from_s: SessionStatus, to_s: SessionStatus
    ) -> None:
        assert_can_transition(from_s, to_s)  # must not raise

    def test_accepts_raw_strings(self) -> None:
        assert_can_transition("pending", "paid")
        assert_can_transition("paid", "claimed")


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    @pytest.mark.parametrize(
        "from_s, to_s",
        [
            # Cannot go backwards
            (SessionStatus.PAID, SessionStatus.PENDING),
            (SessionStatus.CLAIMED, SessionStatus.PENDING),
            (SessionStatus.CLAIMED, SessionStatus.PAID),
            (SessionStatus.EXPIRED, SessionStatus.PENDING),
            (SessionStatus.EXPIRED, SessionStatus.PAID),
            (SessionStatus.EXPIRED, SessionStatus.CLAIMED),
            # Cannot skip states
            (SessionStatus.PENDING, SessionStatus.CLAIMED),
            # Cannot self-transition
            (SessionStatus.PENDING, SessionStatus.PENDING),
            (SessionStatus.PAID, SessionStatus.PAID),
            (SessionStatus.CLAIMED, SessionStatus.CLAIMED),
            (SessionStatus.EXPIRED, SessionStatus.EXPIRED),
        ],
    )
    def test_invalid_transition_raises(
        self, from_s: SessionStatus, to_s: SessionStatus
    ) -> None:
        with pytest.raises(InvalidTransitionError):
            assert_can_transition(from_s, to_s)

    def test_error_carries_state_info(self) -> None:
        with pytest.raises(InvalidTransitionError) as exc_info:
            assert_can_transition(SessionStatus.PENDING, SessionStatus.CLAIMED)
        err = exc_info.value
        assert err.from_status == SessionStatus.PENDING
        assert err.to_status == SessionStatus.CLAIMED
        assert "pending" in str(err).lower()
        assert "claimed" in str(err).lower()

    def test_is_subclass_of_value_error(self) -> None:
        with pytest.raises(ValueError):
            assert_can_transition(SessionStatus.EXPIRED, SessionStatus.PENDING)


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------


class TestIsTerminal:
    def test_claimed_is_terminal(self) -> None:
        assert is_terminal(SessionStatus.CLAIMED) is True

    @pytest.mark.parametrize("s", [SessionStatus.PENDING, SessionStatus.PAID, SessionStatus.EXPIRED])
    def test_non_claimed_not_terminal(self, s: SessionStatus) -> None:
        assert is_terminal(s) is False

    def test_accepts_raw_string(self) -> None:
        assert is_terminal("claimed") is True
        assert is_terminal("pending") is False
