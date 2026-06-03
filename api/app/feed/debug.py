"""Admin/debug formatting for normalized card feed generation."""

from __future__ import annotations

from typing import Literal, Protocol

from .debug_schemas import CardGenerationDebugFinding
from .schemas import CardFeedResponse, CardFeedStatus


class CardFeedDebugResult(Protocol):
    response: CardFeedResponse
    validation_outcomes: tuple
    detail_contract_error: str | None
    generation_error_type: str | None


def debug_findings(
    result: CardFeedDebugResult,
) -> tuple[list[CardGenerationDebugFinding], list[CardGenerationDebugFinding]]:
    warnings: list[CardGenerationDebugFinding] = []
    errors: list[CardGenerationDebugFinding] = []

    response = result.response
    if response.generation.status is CardFeedStatus.stale_regenerating:
        warnings.append(
            _debug_finding(
                code="live_generation_stale_regenerating",
                severity="warning",
                message="Live game cards are available while regeneration is pending.",
                scope="cache",
            )
        )

    if result.detail_contract_error is not None:
        errors.append(
            _debug_finding(
                code="detail_contract_invalid",
                severity="error",
                message=result.detail_contract_error,
                scope="sport_adapter",
            )
        )

    if result.generation_error_type is not None:
        errors.append(
            _debug_finding(
                code="card_generation_failed",
                severity="error",
                message=f"Card generation failed: {result.generation_error_type}",
                scope="generation",
            )
        )

    if (
        response.generation.status is CardFeedStatus.validation_blocked
        and not errors
        and not result.validation_outcomes
    ):
        errors.append(
            _debug_finding(
                code="card_generation_blocked",
                severity="error",
                message=response.generation.validation_issues[0]
                if response.generation.validation_issues
                else "Card generation is blocked by game state.",
                scope="generation",
            )
        )

    for outcome in result.validation_outcomes:
        for finding in outcome.findings:
            target = errors if finding.severity == "error" else warnings
            target.append(
                _debug_finding(
                    code=finding.code,
                    severity=finding.severity,
                    message=finding.message,
                    play_id=outcome.play_id or str(outcome.play_index),
                    scope=(
                        "serialized"
                        if finding.code == "public_card_forbidden_key"
                        else _finding_scope(finding.field)
                    ),
                )
            )

    return warnings, errors


def _debug_finding(
    *,
    code: str,
    severity: Literal["info", "warning", "error"],
    message: str,
    play_id: str | None = None,
    scope: str | None = None,
) -> CardGenerationDebugFinding:
    return CardGenerationDebugFinding(
        code=code,
        severity=severity,
        message=message,
        play_id=play_id,
        scope=scope,
    )


def _finding_scope(field: str | None) -> str:
    if field is None:
        return "card"
    if field.startswith("cards."):
        return "serialized"
    if "." in field:
        return field
    return f"card.{field}"


def debug_status(
    response: CardFeedResponse,
) -> Literal["available", "not_available", "blocked"]:
    if response.generation.status in {
        CardFeedStatus.ready,
        CardFeedStatus.stale_regenerating,
    }:
        return "available"
    if response.generation.status is CardFeedStatus.validation_blocked:
        return "blocked"
    return "not_available"


def debug_reason(
    response: CardFeedResponse,
    result: CardFeedDebugResult,
    status: Literal["available", "not_available", "blocked"],
) -> str | None:
    if status == "available":
        if response.generation.status is CardFeedStatus.stale_regenerating:
            return "Live cards are available from the current source while updates regenerate."
        return None
    if result.detail_contract_error is not None:
        return "Card generation is blocked by sport adapter consistency checks."
    if result.generation_error_type is not None:
        return "Card generation failed before producing public cards."
    reasons = response.generation.validation_issues
    if reasons:
        return reasons[0]
    return {
        CardFeedStatus.no_pbp_yet: "No play-by-play source data is available for this game.",
        CardFeedStatus.unsupported_sport: "Narrative card generation does not support this sport.",
        CardFeedStatus.generation_pending: "Narrative card generation is pending.",
        CardFeedStatus.validation_blocked: "Narrative card generation is blocked.",
    }.get(response.generation.status)


def cache_state(response: CardFeedResponse) -> str:
    if response.generation.is_stale:
        return "stale_regenerating"
    if response.cards:
        return "generated_on_request"
    return "empty"
