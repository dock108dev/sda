"""Typed model for quality-gate regen failure context (ISSUE-054).

Serializes GateDecision.failures into a typed Pydantic model so that the
RENDER_BLOCKS prompt builder cannot silently drop grader dimensions.

Injected into the volatile/data layer of the RENDER_BLOCKS prompt only.
The stable identity layer (narrative rules, style, guardrails) is never touched.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class RegenFailureContext(BaseModel):
    """Structured breakdown of grader failures for the regen prompt.

    Built from GateDecision.failures — a flat list of strings where Tier 2
    rubric entries are prefixed with ``tier2_``. The model partitions them so
    the prompt builder renders each dimension individually and cannot omit any.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tier1_failures: list[str] = Field(default_factory=list)
    tier2_rubric_failures: list[str] = Field(default_factory=list)
    regen_attempt: int = Field(default=1, ge=1)

    @classmethod
    def from_failure_reasons(
        cls,
        reasons: list[str],
        regen_attempt: int = 1,
    ) -> "RegenFailureContext":
        """Build from the flat GateDecision.failures list.

        Args:
            reasons: Flat failure list as returned by ``apply_grade_gate()``.
            regen_attempt: The attempt counter (1 = first regen, etc.).
        """
        tier1: list[str] = []
        tier2: list[str] = []
        for r in reasons:
            (tier2 if r.startswith("tier2_") else tier1).append(r)
        return cls(
            tier1_failures=tier1,
            tier2_rubric_failures=tier2,
            regen_attempt=regen_attempt,
        )

    def has_failures(self) -> bool:
        """True when at least one failure dimension is present."""
        return bool(self.tier1_failures or self.tier2_rubric_failures)

    def render_for_prompt(self) -> str:
        """Human-readable section for injection into the RENDER_BLOCKS data layer.

        Every failure dimension is included — no field can be silently dropped
        because the model owns the list and iterates it explicitly.
        """
        if not self.has_failures():
            return ""

        lines = [
            f"QUALITY FEEDBACK (regen attempt {self.regen_attempt} — previous version failed review):",
            "The previous narrative had the following issues. Address each directly:",
            "",
        ]

        if self.tier1_failures:
            lines.append("Rule failures:")
            for raw in self.tier1_failures:
                lines.append(f"  • {_humanize(raw)}")

        if self.tier2_rubric_failures:
            if self.tier1_failures:
                lines.append("")
            lines.append("Rubric dimension failures (LLM scorer):")
            for raw in self.tier2_rubric_failures:
                lines.append(f"  • {_humanize(raw)}")

        lines.extend([
            "",
            "Do not repeat these patterns. Produce a higher-quality narrative.",
        ])
        return "\n".join(lines)


_LABEL_MAP: dict[str, str] = {
    "block_count": "block count outside required range",
    "word_count": "word count outside limits",
    "score_not_mentioned": "final score not mentioned in narrative",
    "forbidden_phrases": "forbidden AI/cliché phrases detected",
    "team_names_missing": "team names absent from narrative",
    "generic_phrase_matches": "generic filler phrases exceed threshold",
    "tier2_factual_accuracy_low_score": "factual accuracy — low score",
    "tier2_sport_specific_voice_low_score": "sport-specific voice — low score",
    "tier2_narrative_coherence_low_score": "narrative coherence — low score",
    "tier2_no_generic_filler_low_score": "no generic filler — low score",
}


def _humanize(raw: str) -> str:
    """Map a raw failure string to readable text, preserving detail suffix."""
    for key, label in _LABEL_MAP.items():
        if raw.startswith(key):
            detail = raw[len(key):].lstrip(":= ").strip()
            return f"{label} ({detail})" if detail else label
    return raw
