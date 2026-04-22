"""Onboarding session state machine — pure logic, no DB coupling.

States: pending → paid → claimed
        any    → expired  (TTL job)

Guards:
  pending → paid     : webhook handler only (no extra guard here; caller is responsible)
  paid    → claimed  : valid claim_token required (caller must verify token match)
  any     → expired  : TTL job only
"""

from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    CLAIMED = "claimed"
    EXPIRED = "expired"


# (from_status, to_status) → allowed
_VALID_TRANSITIONS: frozenset[tuple[SessionStatus, SessionStatus]] = frozenset(
    {
        (SessionStatus.PENDING, SessionStatus.PAID),
        (SessionStatus.PAID, SessionStatus.CLAIMED),
        (SessionStatus.PENDING, SessionStatus.EXPIRED),
        (SessionStatus.PAID, SessionStatus.EXPIRED),
        (SessionStatus.CLAIMED, SessionStatus.EXPIRED),
    }
)


class InvalidTransitionError(ValueError):
    """Raised when a state transition is not permitted."""

    def __init__(self, from_status: SessionStatus, to_status: SessionStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Cannot transition onboarding session from '{from_status}' to '{to_status}'"
        )


def assert_can_transition(
    current: SessionStatus | str, target: SessionStatus | str
) -> None:
    """Raise InvalidTransitionError if the transition is not permitted.

    Accepts both SessionStatus values and raw strings for convenience.
    """
    current_s = SessionStatus(current)
    target_s = SessionStatus(target)
    if (current_s, target_s) not in _VALID_TRANSITIONS:
        raise InvalidTransitionError(current_s, target_s)


def is_terminal(status: SessionStatus | str) -> bool:
    """Return True for states that cannot advance further (claimed)."""
    return SessionStatus(status) == SessionStatus.CLAIMED
