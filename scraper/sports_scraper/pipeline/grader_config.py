"""Configuration and prompts for the narrative quality grader."""

from __future__ import annotations

# ── Thresholds ────────────────────────────────────────────────────────────────

ESCALATION_THRESHOLD: float = 60.0
TIER2_CACHE_TTL: int = 604800  # 7 days in seconds

# Sonnet escalation: Haiku scores in this band trigger a Sonnet re-grade.
# Below LOW → fail fast (skip Sonnet). Above HIGH → pass fast (skip Sonnet).
SONNET_AMBIGUOUS_BAND_LOW: float = 40.0
SONNET_AMBIGUOUS_BAND_HIGH: float = 60.0
SONNET_MODEL: str = "claude-sonnet-4-6"

# Block count bounds (mirror validate_blocks.py constants)
MIN_BLOCKS: int = 3
MAX_BLOCKS: int = 7

# Word count bounds per block and for the whole flow
MIN_WORDS_PER_BLOCK: int = 30
MAX_WORDS_PER_BLOCK: int = 120
MAX_TOTAL_WORDS: int = 600

# Combined score weights when both tiers are available
_TIER1_WEIGHT: float = 0.4
_TIER2_WEIGHT: float = 0.6

# ── Forbidden phrases ─────────────────────────────────────────────────────────
# Phrases that indicate LLM artifacts, non-specificity, or clichéd writing.
# These should never appear in a published game recap.

FORBIDDEN_PHRASES: list[str] = [
    "as an ai",
    "as an ai language model",
    "i cannot",
    "i'm unable",
    "i am unable",
    "in conclusion,",
    "in conclusion.",
    "to summarize,",
    "to summarize.",
    "as we all know",
    "needless to say",
    "it is worth noting",
    "it is important to note",
    "it goes without saying",
    "at the end of the day",
    "the game saw",
    "had a great game",
    "played really well",
    "showed up to play",
]

# ── LLM rubric prompt ─────────────────────────────────────────────────────────

_LLM_RUBRIC_PROMPT = """\
You are a sports narrative quality evaluator. Score the following game recap.

Game context:
- Sport: {sport}
- Teams: {away_team} @ {home_team}
- Final score: {home_team} {home_score}, {away_team} {away_score}

Narrative (all blocks combined):
---
{narrative}
---

Score each dimension from 0 to 25 (integer only). Output ONLY valid JSON with this exact shape:
{{
  "factual_accuracy": <0-25>,
  "sport_specific_voice": <0-25>,
  "narrative_coherence": <0-25>,
  "no_generic_filler": <0-25>,
  "reasoning": "<one sentence>"
}}

Rubric:
- factual_accuracy (0-25): Do scores, team names, and player references match the game context?
- sport_specific_voice (0-25): Does the language use {sport}-appropriate terminology? Reads like a professional recap?
- narrative_coherence (0-25): Clear arc from setup to resolution? Logical transitions between blocks?
- no_generic_filler (0-25): Concrete and specific to this game (not generic sports clichés)?
"""

# Sonnet prompt uses chain-of-thought reasoning before scoring; same output schema.
_LLM_RUBRIC_SONNET_PROMPT = """\
You are a sports narrative quality evaluator. Score the following game recap using \
step-by-step reasoning before each score.

Game context:
- Sport: {sport}
- Teams: {away_team} @ {home_team}
- Final score: {home_team} {home_score}, {away_team} {away_score}

Narrative (all blocks combined):
---
{narrative}
---

For EACH dimension: quote the relevant passage, compare to game context, identify issues, \
then assign a score.

BIAS WARNING: default to 15/25; only award >20 with specific quoted evidence; \
only award <10 on clear failure.

Output ONLY valid JSON with this exact shape:
{{
  "factual_accuracy": <0-25>,
  "factual_accuracy_reasoning": "<one sentence>",
  "sport_specific_voice": <0-25>,
  "sport_specific_voice_reasoning": "<one sentence>",
  "narrative_coherence": <0-25>,
  "narrative_coherence_reasoning": "<one sentence>",
  "no_generic_filler": <0-25>,
  "no_generic_filler_reasoning": "<one sentence>",
  "reasoning": "<overall one sentence>"
}}

Rubric:
- factual_accuracy (0-25): Do scores, team names, and player references match the game context?
- sport_specific_voice (0-25): Does the language use {sport}-appropriate terminology? Reads like a professional recap?
- narrative_coherence (0-25): Clear arc from setup to resolution? Logical transitions between blocks?
- no_generic_filler (0-25): Concrete and specific to this game (not generic sports clichés)?
"""

# ── Data classes ──────────────────────────────────────────────────────────────
