"""Result models for narrative quality grading."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TierOneResult:
    """Result of Tier 1 rule-based checks."""

    score: float
    failures: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass
class TierTwoResult:
    """Result of Tier 2 LLM scoring."""

    score: float
    rubric: dict[str, float] = field(default_factory=dict)
    cache_hit: bool = False
    model: str = "claude-haiku-4-5-20251001"


@dataclass
class GraderResult:
    """Combined output of all grader tiers."""

    flow_id: int
    sport: str
    tier1: TierOneResult
    tier2: TierTwoResult | None
    combined_score: float
    escalated: bool
    is_template_fallback: bool = False
    # Sonnet escalation fields (populated only when Haiku score was ambiguous)
    tier2_sonnet: TierTwoResult | None = None
    haiku_ambiguous: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────
