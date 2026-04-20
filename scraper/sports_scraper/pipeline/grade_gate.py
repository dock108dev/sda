"""Grade gate: decision logic for the 3-tier quality gate (ISSUE-053).

Converts a GraderResult into a publish / regen / template_fallback decision.
One regen attempt is allowed; a second failure forces template fallback and
human escalation.

Gate threshold is intentionally separate from ESCALATION_THRESHOLD so the
two concerns (pipeline gate vs. human-review escalation) can be tuned
independently without conflating them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .grader import GraderResult

GATE_THRESHOLD: float = 60.0
# Only one regen attempt is permitted before falling back to templates.
MAX_REGEN_ATTEMPTS: int = 1


@dataclass
class GateDecision:
    """Outcome of the grade gate check.

    Attributes:
        action: What the pipeline should do next.
        failures: Structured list of failure reasons from the grader's
            Tier 1 result (and Tier 2 rubric when available).  These are
            passed as-is to the regen Celery task so the next generation
            attempt can incorporate them as prompt context.
        combined_score: The combined grade that triggered this decision.
    """

    action: Literal["publish", "regen", "template_fallback"]
    failures: list[str] = field(default_factory=list)
    combined_score: float = 0.0


def apply_grade_gate(
    grader_result: "GraderResult | None",
    regen_attempt: int = 0,
    threshold: float = GATE_THRESHOLD,
) -> GateDecision:
    """Apply the quality gate and return a publish/regen/template_fallback decision.

    Args:
        grader_result: Result from ``grade_flow()``.  ``None`` means the flow
            was produced by the deterministic template path; those flows are
            always published without a quality check.
        regen_attempt: How many regen attempts have already run for this
            game (0 = first pipeline pass; 1 = first regen; etc.).
        threshold: Combined score floor for publishing.
            Defaults to GATE_THRESHOLD (60.0).

    Returns:
        GateDecision with the action the pipeline should take next.
    """
    # Template-generated flows carry no LLM quality signal — always publish.
    if grader_result is None:
        return GateDecision(action="publish", failures=[], combined_score=100.0)

    failures: list[str] = list(grader_result.tier1.failures)

    # Use Sonnet rubric when available (more accurate for ambiguous cases);
    # fall back to Haiku rubric otherwise.
    effective_t2 = (
        getattr(grader_result, "tier2_sonnet", None) or grader_result.tier2
    )
    if effective_t2 and effective_t2.rubric:
        for dim, score in effective_t2.rubric.items():
            if score < 12:  # below 48 % of the 25-point max per dimension
                failures.append(f"tier2_{dim}_low_score:{score:.0f}/25")

    score = grader_result.combined_score
    if score >= threshold:
        return GateDecision(action="publish", failures=failures, combined_score=score)

    if regen_attempt < MAX_REGEN_ATTEMPTS:
        return GateDecision(action="regen", failures=failures, combined_score=score)

    return GateDecision(
        action="template_fallback", failures=failures, combined_score=score
    )
