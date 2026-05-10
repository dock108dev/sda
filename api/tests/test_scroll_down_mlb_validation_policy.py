"""Validation severity policy tests.

Live decks ship with warnings; official decks fail closed on errors. This
test pins the policy split at the service layer so a future port of the
validator can't change the user-visible behavior accidentally.
"""

from __future__ import annotations

from app.scroll_down_mlb.schemas import (
    GenerationPolicy,
    ValidationSeverity,
    ValidationWarning,
)
from app.scroll_down_mlb.service import apply_validation_policy


def _err(code: str = "home_run_without_score_delta") -> ValidationWarning:
    return ValidationWarning(
        code=code,
        severity=ValidationSeverity.error,
        message="boom",
    )


def _warn(code: str = "runner_label_not_on_rendered_base") -> ValidationWarning:
    return ValidationWarning(
        code=code,
        severity=ValidationSeverity.warning,
        message="meh",
    )


def test_official_policy_blocks_on_error() -> None:
    warnings, errors, blocked = apply_validation_policy(
        [_err()],
        GenerationPolicy.official,
    )
    assert blocked is True
    assert len(errors) == 1
    assert errors[0].severity is ValidationSeverity.error
    assert warnings == []


def test_official_policy_does_not_block_on_warning_only() -> None:
    warnings, errors, blocked = apply_validation_policy(
        [_warn()],
        GenerationPolicy.official,
    )
    assert blocked is False
    assert errors == []
    assert len(warnings) == 1


def test_live_policy_downgrades_errors_to_warnings() -> None:
    """Mid-game we never blank out. A finding that would block official
    generation is downgraded to a warning so the live deck still ships."""
    warnings, errors, blocked = apply_validation_policy(
        [_err(), _err("strikeout_without_out_increment")],
        GenerationPolicy.live,
    )
    assert blocked is False
    assert errors == []
    assert len(warnings) == 2
    assert all(w.severity is ValidationSeverity.warning for w in warnings)


def test_live_policy_preserves_native_warnings_unchanged() -> None:
    findings = [_warn(), _warn("movement_path_missing_for_runner_change")]
    warnings, errors, blocked = apply_validation_policy(
        findings,
        GenerationPolicy.live,
    )
    assert blocked is False
    assert errors == []
    assert len(warnings) == 2


def test_mixed_findings_under_official_policy() -> None:
    warnings, errors, blocked = apply_validation_policy(
        [_warn(), _err(), _warn("runner_label_not_on_rendered_base")],
        GenerationPolicy.official,
    )
    assert blocked is True
    assert len(errors) == 1
    assert len(warnings) == 2


def test_empty_findings_never_blocks() -> None:
    for policy in (GenerationPolicy.live, GenerationPolicy.official):
        warnings, errors, blocked = apply_validation_policy([], policy)
        assert blocked is False
        assert errors == []
        assert warnings == []
