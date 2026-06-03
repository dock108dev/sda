"""Timeline validation rules.

Implements validation from docs/TIMELINE_VALIDATION.md.
Bad timelines never ship.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .timeline_types import PHASE_ORDER

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    name: str
    passed: bool
    message: str | None = None
    details: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Complete validation report for a timeline."""

    game_id: int
    critical_checks: list[ValidationResult] = field(default_factory=list)
    warning_checks: list[ValidationResult] = field(default_factory=list)

    @property
    def critical_passed(self) -> int:
        return sum(1 for c in self.critical_checks if c.passed)

    @property
    def critical_failed(self) -> int:
        return sum(1 for c in self.critical_checks if not c.passed)

    @property
    def warnings_count(self) -> int:
        return sum(1 for c in self.warning_checks if not c.passed)

    @property
    def verdict(self) -> str:
        if self.critical_failed > 0:
            return "FAIL"
        elif self.warnings_count > 0:
            return "PASS_WITH_WARNINGS"
        else:
            return "PASS"

    @property
    def is_valid(self) -> bool:
        """Returns True if timeline can be persisted."""
        return self.critical_failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "verdict": self.verdict,
            "critical": {
                "passed": self.critical_passed,
                "failed": self.critical_failed,
                "checks": [
                    {
                        "name": c.name,
                        "status": "pass" if c.passed else "fail",
                        "message": c.message,
                        "details": c.details[:5],  # Limit details
                    }
                    for c in self.critical_checks
                ],
            },
            "warnings": {
                "count": self.warnings_count,
                "checks": [
                    {
                        "name": c.name,
                        "status": "pass" if c.passed else "warn",
                        "message": c.message,
                        "details": c.details[:5],
                    }
                    for c in self.warning_checks
                    if not c.passed
                ],
            },
        }


class TimelineValidationError(Exception):
    """Raised when timeline validation fails."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        failed_checks = [c.name for c in report.critical_checks if not c.passed]
        super().__init__(f"Timeline validation failed: {', '.join(failed_checks)}")


# =============================================================================
# CRITICAL CHECKS - Must pass, blocks persistence
# =============================================================================


def check_not_empty(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """C1: Timeline must have at least one event."""
    if len(timeline) == 0:
        return ValidationResult(
            name="C1_not_empty",
            passed=False,
            message="Timeline is empty",
        )

    pbp_count = sum(1 for e in timeline if e.get("event_type") == "pbp")
    if pbp_count == 0:
        return ValidationResult(
            name="C1_not_empty",
            passed=False,
            message="Timeline has no PBP events",
        )

    return ValidationResult(
        name="C1_not_empty",
        passed=True,
        message=f"Timeline has {len(timeline)} events ({pbp_count} PBP)",
    )


def check_phase_order(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """C2: Phase order must be monotonically non-decreasing."""
    last_phase_order = -1
    last_phase = None
    violations: list[str] = []

    for i, event in enumerate(timeline):
        phase = event.get("phase")
        if phase is None:
            continue

        current_order = PHASE_ORDER.get(phase, 50)

        if current_order < last_phase_order:
            violations.append(
                f"Event {i}: {phase} (order {current_order}) after {last_phase} (order {last_phase_order})"
            )

        if current_order > last_phase_order:
            last_phase_order = current_order
            last_phase = phase

    if violations:
        return ValidationResult(
            name="C2_phase_order",
            passed=False,
            message=f"Phase order violated {len(violations)} times",
            details=violations[:10],
        )

    return ValidationResult(
        name="C2_phase_order",
        passed=True,
        message="Phase order is monotonic",
    )


def check_no_duplicates(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """C3: No duplicate events."""
    seen: set[tuple[str, ...]] = set()
    duplicates: list[str] = []

    for i, event in enumerate(timeline):
        event_type = event.get("event_type", "unknown")

        if event_type == "pbp":
            key = ("pbp", str(event.get("play_index")))
        elif event_type == "tweet":
            key = (
                "tweet",
                event.get("synthetic_timestamp", ""),
                event.get("author", ""),
            )
        elif event_type == "odds":
            key = (
                "odds",
                event.get("odds_type", ""),
                event.get("book", ""),
            )
        else:
            key = ("other", str(i))

        if key in seen:
            duplicates.append(f"Event {i}: {key}")
        seen.add(key)

    if duplicates:
        return ValidationResult(
            name="C3_no_duplicates",
            passed=False,
            message=f"Found {len(duplicates)} duplicate events",
            details=duplicates[:10],
        )

    return ValidationResult(
        name="C3_no_duplicates",
        passed=True,
        message="No duplicate events",
    )


def check_social_has_phase(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """C4: All social events must have a phase assigned."""
    missing_phase: list[str] = []

    for i, event in enumerate(timeline):
        if event.get("event_type") != "tweet":
            continue

        phase = event.get("phase")
        if phase is None or phase == "":
            missing_phase.append(
                f"Event {i}: tweet by {event.get('author', 'unknown')} at {event.get('synthetic_timestamp', '?')}"
            )

    if missing_phase:
        return ValidationResult(
            name="C4_social_has_phase",
            passed=False,
            message=f"{len(missing_phase)} social events missing phase",
            details=missing_phase[:10],
        )

    return ValidationResult(
        name="C4_social_has_phase",
        passed=True,
        message="All social events have phase",
    )


def check_social_has_content(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """C5: No social events with null/empty content."""
    empty_content: list[str] = []

    for i, event in enumerate(timeline):
        if event.get("event_type") != "tweet":
            continue

        text = event.get("text")
        if text is None or (isinstance(text, str) and text.strip() == ""):
            empty_content.append(
                f"Event {i}: tweet by {event.get('author', 'unknown')} has null/empty text"
            )

    if empty_content:
        return ValidationResult(
            name="C5_social_has_content",
            passed=False,
            message=f"{len(empty_content)} social events with null/empty content",
            details=empty_content[:10],
        )

    return ValidationResult(
        name="C5_social_has_content",
        passed=True,
        message="All social events have content",
    )


def check_timestamps_monotonic(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """C6: PBP timestamps must be non-decreasing within each phase.

    Note: Tweet timestamps are wall-clock times and may interleave with
    PBP synthetic timestamps. We only check PBP-to-PBP ordering.
    """
    violations: list[str] = []

    # Group PBP events by phase
    pbp_by_phase: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for i, event in enumerate(timeline):
        if event.get("event_type") != "pbp":
            continue
        phase = event.get("phase", "unknown")
        pbp_by_phase.setdefault(phase, []).append((i, event))

    for phase, events in pbp_by_phase.items():
        last_ts: datetime | None = None
        last_idx: int = -1

        for i, event in events:
            ts_str = event.get("synthetic_timestamp")
            if not ts_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if last_ts is not None and ts < last_ts:
                violations.append(
                    f"Phase {phase}, PBP event {i}: {ts_str} < event {last_idx}"
                )

            last_ts = ts
            last_idx = i

    if violations:
        return ValidationResult(
            name="C6_timestamps_monotonic",
            passed=False,
            message=f"PBP timestamp regression in {len(violations)} cases",
            details=violations[:10],
        )

    return ValidationResult(
        name="C6_timestamps_monotonic",
        passed=True,
        message="PBP timestamps are monotonic within phases",
    )


# =============================================================================
# WARNING CHECKS - Log but don't block
# =============================================================================


def check_social_has_role(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """W1: Social events should have a role assigned."""
    missing_role: list[str] = []

    for i, event in enumerate(timeline):
        if event.get("event_type") != "tweet":
            continue

        role = event.get("role")
        if role is None:
            missing_role.append(f"Event {i}: tweet by {event.get('author', 'unknown')}")

    if missing_role:
        return ValidationResult(
            name="W1_social_has_role",
            passed=False,
            message=f"{len(missing_role)} social events missing role",
            details=missing_role[:10],
        )

    return ValidationResult(
        name="W1_social_has_role",
        passed=True,
        message="All social events have role",
    )


def check_phase_coverage(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """W2: Timeline should have events in expected phases."""
    phases_present = set(e.get("phase") for e in timeline if e.get("phase"))

    expected_game_phases = {"q1", "q2", "q3", "q4"}
    missing = expected_game_phases - phases_present

    if missing:
        return ValidationResult(
            name="W2_phase_coverage",
            passed=False,
            message=f"Missing expected phases: {missing}",
            details=[f"Expected: {expected_game_phases}", f"Present: {phases_present}"],
        )

    return ValidationResult(
        name="W2_phase_coverage",
        passed=True,
        message=f"All game phases present: {sorted(phases_present)}",
    )


def check_odds_has_phase(timeline: Sequence[dict[str, Any]]) -> ValidationResult:
    """W4: All odds events must have a phase assigned."""
    missing_phase: list[str] = []

    for i, event in enumerate(timeline):
        if event.get("event_type") != "odds":
            continue

        phase = event.get("phase")
        if phase is None or phase == "":
            missing_phase.append(
                f"Event {i}: odds {event.get('odds_type', 'unknown')} from {event.get('book', '?')}"
            )

    if missing_phase:
        return ValidationResult(
            name="W4_odds_has_phase",
            passed=False,
            message=f"{len(missing_phase)} odds events missing phase",
            details=missing_phase[:10],
        )

    return ValidationResult(
        name="W4_odds_has_phase",
        passed=True,
        message="All odds events have phase",
    )


def check_summary_phases_valid(
    timeline: Sequence[dict[str, Any]],
    summary: dict[str, Any],
) -> ValidationResult:
    """W3: Summary should only reference phases present in timeline."""
    timeline_phases = set(e.get("phase") for e in timeline if e.get("phase"))
    summary_phases = set(summary.get("phases_in_timeline", []))

    # Check if summary phases match timeline phases
    if summary_phases and summary_phases != timeline_phases:
        return ValidationResult(
            name="W3_summary_phases_valid",
            passed=False,
            message="Summary phases don't match timeline phases",
            details=[
                f"Timeline: {sorted(timeline_phases)}",
                f"Summary: {sorted(summary_phases)}",
            ],
        )

    return ValidationResult(
        name="W3_summary_phases_valid",
        passed=True,
        message="Summary phases match timeline",
    )


def validate_timeline(
    timeline: Sequence[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    game_id: int = 0,
) -> ValidationReport:
    """
    Validate a timeline against all rules.

    Returns a ValidationReport with all check results.

    Critical checks that fail will cause is_valid to be False,
    blocking persistence.
    """
    report = ValidationReport(game_id=game_id)

    # Critical checks
    report.critical_checks.append(check_not_empty(timeline))
    report.critical_checks.append(check_phase_order(timeline))
    report.critical_checks.append(check_no_duplicates(timeline))
    report.critical_checks.append(check_social_has_phase(timeline))
    report.critical_checks.append(check_social_has_content(timeline))
    report.critical_checks.append(check_timestamps_monotonic(timeline))

    # Warning checks
    report.warning_checks.append(check_social_has_role(timeline))
    report.warning_checks.append(check_phase_coverage(timeline))
    report.warning_checks.append(check_odds_has_phase(timeline))

    if summary:
        report.warning_checks.append(check_summary_phases_valid(timeline, summary))

    return report


def validate_and_log(
    timeline: Sequence[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    game_id: int = 0,
) -> ValidationReport:
    """
    Validate timeline and log results.

    Raises TimelineValidationError if critical checks fail.
    """
    report = validate_timeline(timeline, summary, game_id)

    if report.verdict == "FAIL":
        logger.error(
            "timeline_validation_failed",
            extra=report.to_dict(),
        )
        raise TimelineValidationError(report)
    if report.verdict == "PASS_WITH_WARNINGS":
        logger.warning(
            "timeline_validation_warnings",
            extra=report.to_dict(),
        )
    else:
        logger.info(
            "timeline_validation_passed",
            extra={"game_id": game_id, "verdict": report.verdict},
        )

    return report
