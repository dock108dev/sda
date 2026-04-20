"""3-tier narrative quality grader for game flow records.

Architecture
============

Tier 1 (always runs, sync, <50ms):
    Rule-based checks: block count, word length per block, total word count,
    forbidden-phrase detection, team-name consistency, and final-score presence.
    Returns a 0–100 score component.

Tier 2 (called from async Celery task, cached):
    LLM scorer via Claude Haiku. Structured rubric covers four dimensions:
    factual accuracy, sport-specific voice, narrative coherence, and absence of
    generic filler. Result is cached in Redis per (flow_id, prompt_hash) to avoid
    redundant API spend; TTL is 7 days.

Tier 3 (escalation):
    Flows whose combined score falls below ESCALATION_THRESHOLD (default 60)
    are written to the quality_review_queue table for human review.

Template-fallback flows:
    When is_template_fallback=True, grade_flow() returns None immediately.
    Template flows are deterministic outputs, not LLM-generated narratives;
    there is no meaningful quality signal to grade, and human review of the
    templates would not improve per-game outcomes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from .grader_rules.generic_phrases import (
    DENSITY_THRESHOLD,
    GENERIC_PHRASE_WEIGHT,
    detect_per_block as _detect_generic_per_block,
    phrase_density as _generic_phrase_density,
)

logger = logging.getLogger(__name__)

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


def _count_words(text: str) -> int:
    return len(text.split())


def _all_block_narratives(blocks: list[dict]) -> str:
    return " ".join(b.get("narrative", "") for b in blocks)


def _compute_prompt_hash(blocks: list[dict], game_data: dict) -> str:
    """Stable 16-char hex hash over scoring inputs for cache keying."""
    payload = json.dumps(
        {
            "blocks": blocks,
            "game": {
                k: game_data.get(k)
                for k in ("sport", "home_team", "away_team", "home_score", "away_score")
            },
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── Tier 1 ────────────────────────────────────────────────────────────────────


def grade_tier1(blocks: list[dict], game_data: dict) -> TierOneResult:
    """Run rule-based Tier 1 checks.

    Designed to complete in < 50ms for any valid flow size.

    Args:
        blocks: List of block dicts from the flow's blocks_json.
        game_data: Source-of-truth values with keys: sport, home_team, away_team,
            home_score (int|None), away_score (int|None).

    Returns:
        TierOneResult with a 0–100 score and per-check details.
    """
    failures: list[str] = []
    checks: dict[str, bool] = {}

    # 1. Block count
    n_blocks = len(blocks)
    ok = MIN_BLOCKS <= n_blocks <= MAX_BLOCKS
    checks["block_count"] = ok
    if not ok:
        failures.append(f"block_count={n_blocks} outside [{MIN_BLOCKS},{MAX_BLOCKS}]")

    # 2. Per-block word length
    lengths_ok = True
    for i, block in enumerate(blocks):
        narrative = block.get("narrative", "")
        words = _count_words(narrative)
        if not narrative or words < MIN_WORDS_PER_BLOCK:
            failures.append(f"block[{i}] too short ({words} words, min {MIN_WORDS_PER_BLOCK})")
            lengths_ok = False
        elif words > MAX_WORDS_PER_BLOCK:
            failures.append(f"block[{i}] too long ({words} words, max {MAX_WORDS_PER_BLOCK})")
            lengths_ok = False
    checks["block_word_lengths"] = lengths_ok

    # 3. Total word count
    combined = _all_block_narratives(blocks)
    total_words = _count_words(combined)
    ok = total_words <= MAX_TOTAL_WORDS
    checks["total_words"] = ok
    if not ok:
        failures.append(f"total_words={total_words} exceeds max {MAX_TOTAL_WORDS}")

    # 4. Forbidden phrases
    combined_lower = combined.lower()
    found: list[str] = [p for p in FORBIDDEN_PHRASES if p in combined_lower]
    ok = len(found) == 0
    checks["forbidden_phrases"] = ok
    if not ok:
        failures.append(f"forbidden_phrases={found}")

    # 5. Team name consistency
    home = game_data.get("home_team", "")
    away = game_data.get("away_team", "")
    if home or away:
        low = combined_lower
        home_present = home.lower() in low if home else True
        away_present = away.lower() in low if away else True
        ok = home_present and away_present
        checks["team_name_consistency"] = ok
        if not ok:
            missing = [t for t, p in [(home, home_present), (away, away_present)] if not p]
            failures.append(f"team_names_missing={missing}")
    else:
        checks["team_name_consistency"] = True

    # 6. Final score appears in narrative (basic consistency signal)
    h_score = game_data.get("home_score")
    a_score = game_data.get("away_score")
    if h_score is not None and a_score is not None:
        pattern = (
            rf"\b{int(h_score)}[\-\u2013]{int(a_score)}\b"
            rf"|\b{int(a_score)}[\-\u2013]{int(h_score)}\b"
        )
        ok = bool(re.search(pattern, combined))
        checks["score_consistency"] = ok
        if not ok:
            failures.append(f"score_not_mentioned: expected {h_score}-{a_score}")
    else:
        checks["score_consistency"] = True

    # 7. RESOLUTION specificity: validate_blocks stamps the flag when the RESOLUTION
    # block has no traceable final-window play reference. Read it from persisted
    # blocks_json so the grader doesn't need PBP access at grade time.
    resolution_block = next(
        (b for b in reversed(blocks) if b.get("role") == "RESOLUTION"), None
    )
    if resolution_block is not None:
        ok = not resolution_block.get("resolution_specificity_warning", False)
        checks["resolution_specificity"] = ok
        if not ok:
            failures.append(
                "resolution_specificity: RESOLUTION block lacks traceable final-window play reference"
            )

    n = len(checks)
    base_score = round((sum(1 for v in checks.values() if v) / n) * 100, 1) if n else 100.0

    # Generic phrase penalty: deduct GENERIC_PHRASE_WEIGHT per match per block.
    # Per-block scoring (not binary) so a single phrase doesn't kill the whole flow.
    total_matches = sum(len(_detect_generic_per_block(b.get("narrative", ""))) for b in blocks)
    if total_matches > 0:
        deduction = round(total_matches * GENERIC_PHRASE_WEIGHT, 1)
        failures.append(
            f"generic_phrase_matches={total_matches} (deduction={deduction} pts)"
        )

    score = max(0.0, round(base_score - total_matches * GENERIC_PHRASE_WEIGHT, 1))
    return TierOneResult(score=score, failures=failures, checks=checks)


# ── Tier 2 ────────────────────────────────────────────────────────────────────


def grade_tier2_cached(
    flow_id: int,
    blocks: list[dict],
    game_data: dict,
    redis_client: object,
) -> TierTwoResult:
    """Run LLM-based Tier 2 scoring with Redis caching.

    Args:
        flow_id: PK of the SportsGameFlow record; used in the cache key.
        blocks: Block dicts from the flow.
        game_data: Dict with keys: sport, home_team, away_team, home_score, away_score.
        redis_client: Connected redis.Redis instance.

    Returns:
        TierTwoResult. cache_hit=True when result is served from cache.
    """
    prompt_hash = _compute_prompt_hash(blocks, game_data)
    cache_key = f"grader:t2:{flow_id}:{prompt_hash}"

    cached = redis_client.get(cache_key)  # type: ignore[union-attr]
    if cached:
        try:
            data = json.loads(cached)
            return TierTwoResult(
                score=float(data["score"]),
                rubric=data.get("rubric", {}),
                cache_hit=True,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "grader_t2_cache_parse_error",
                exc_info=True,
                extra={"flow_id": flow_id},
            )

    import anthropic

    model = "claude-haiku-4-5-20251001"
    narrative = _all_block_narratives(blocks)
    prompt = _LLM_RUBRIC_PROMPT.format(
        sport=game_data.get("sport", ""),
        home_team=game_data.get("home_team", ""),
        away_team=game_data.get("away_team", ""),
        home_score=game_data.get("home_score", ""),
        away_score=game_data.get("away_score", ""),
        narrative=narrative,
    )

    rubric: dict[str, float] = {}
    score = 0.0
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
        parsed = json.loads(raw)
        dims = ["factual_accuracy", "sport_specific_voice", "narrative_coherence", "no_generic_filler"]
        for dim in dims:
            rubric[dim] = float(min(max(parsed.get(dim, 0), 0), 25))
        score = round(sum(rubric.values()), 1)
    except Exception:
        logger.warning(
            "grader_t2_llm_call_failed",
            exc_info=True,
            extra={"flow_id": flow_id, "model": model},
        )
        # Neutral score on LLM failure; pipeline is not blocked
        score = 50.0
        rubric = {}

    result = TierTwoResult(score=score, rubric=rubric, cache_hit=False, model=model)
    try:
        redis_client.setex(  # type: ignore[union-attr]
            cache_key,
            TIER2_CACHE_TTL,
            json.dumps({"score": score, "rubric": rubric}),
        )
    except Exception:
        logger.warning(
            "grader_t2_cache_write_failed",
            exc_info=True,
            extra={"flow_id": flow_id},
        )
    return result


def grade_tier2_sonnet_cached(
    flow_id: int,
    blocks: list[dict],
    game_data: dict,
    redis_client: object,
) -> TierTwoResult:
    """Run Sonnet-based Tier 2 scoring with Redis caching.

    Called only when Haiku score falls within the ambiguous band
    [SONNET_AMBIGUOUS_BAND_LOW, SONNET_AMBIGUOUS_BAND_HIGH].
    Uses chain-of-thought reasoning for higher accuracy on borderline cases.

    Args:
        flow_id: PK of the SportsGameFlow record; used in the cache key.
        blocks: Block dicts from the flow.
        game_data: Dict with keys: sport, home_team, away_team, home_score, away_score.
        redis_client: Connected redis.Redis instance.

    Returns:
        TierTwoResult. cache_hit=True when result is served from cache.
    """
    prompt_hash = _compute_prompt_hash(blocks, game_data)
    cache_key = f"grader:t2s:{flow_id}:{prompt_hash}"  # 't2s' = tier2 sonnet

    cached = redis_client.get(cache_key)  # type: ignore[union-attr]
    if cached:
        try:
            data = json.loads(cached)
            return TierTwoResult(
                score=float(data["score"]),
                rubric=data.get("rubric", {}),
                cache_hit=True,
                model=SONNET_MODEL,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning(
                "grader_t2s_cache_parse_error",
                exc_info=True,
                extra={"flow_id": flow_id},
            )

    import anthropic

    narrative = _all_block_narratives(blocks)
    prompt = _LLM_RUBRIC_SONNET_PROMPT.format(
        sport=game_data.get("sport", ""),
        home_team=game_data.get("home_team", ""),
        away_team=game_data.get("away_team", ""),
        home_score=game_data.get("home_score", ""),
        away_score=game_data.get("away_score", ""),
        narrative=narrative,
    )

    rubric: dict[str, float] = {}
    score = 0.0
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
        parsed = json.loads(raw)
        dims = ["factual_accuracy", "sport_specific_voice", "narrative_coherence", "no_generic_filler"]
        for dim in dims:
            rubric[dim] = float(min(max(parsed.get(dim, 0), 0), 25))
        score = round(sum(rubric.values()), 1)
    except Exception:
        logger.warning(
            "grader_t2s_llm_call_failed",
            exc_info=True,
            extra={"flow_id": flow_id, "model": SONNET_MODEL},
        )
        # Neutral score on LLM failure; pipeline is not blocked
        score = 50.0
        rubric = {}

    result = TierTwoResult(score=score, rubric=rubric, cache_hit=False, model=SONNET_MODEL)
    try:
        redis_client.setex(  # type: ignore[union-attr]
            cache_key,
            TIER2_CACHE_TTL,
            json.dumps({"score": score, "rubric": rubric}),
        )
    except Exception:
        logger.warning(
            "grader_t2s_cache_write_failed",
            exc_info=True,
            extra={"flow_id": flow_id},
        )
    return result


# ── Combined ──────────────────────────────────────────────────────────────────


def compute_combined_score(t1: TierOneResult, t2: TierTwoResult | None) -> float:
    """Weighted 0–100 combined score.

    Uses both tiers when Tier 2 is available; degrades to Tier 1 alone otherwise.
    """
    if t2 is None:
        return round(t1.score, 1)
    return round(_TIER1_WEIGHT * t1.score + _TIER2_WEIGHT * t2.score, 1)


def grade_flow(
    flow_id: int,
    sport: str,
    blocks: list[dict],
    game_data: dict,
    redis_client: object,
    is_template_fallback: bool = False,
    threshold: float = ESCALATION_THRESHOLD,
    sonnet_band_low: float = SONNET_AMBIGUOUS_BAND_LOW,
    sonnet_band_high: float = SONNET_AMBIGUOUS_BAND_HIGH,
) -> GraderResult | None:
    """Run the full 3-tier grader on a flow record.

    Tier 1 (rule-based) always runs.
    Tier 2 Haiku always runs.
    Tier 2 Sonnet runs only when Haiku score is in [sonnet_band_low, sonnet_band_high]
    (the ambiguous band); otherwise Haiku result is used directly.

    Args:
        flow_id: PK of the SportsGameFlow record.
        sport: League code (e.g. "NBA").
        blocks: blocks_json from the flow record.
        game_data: Source-of-truth values: home_team, away_team, home_score,
            away_score, sport.
        redis_client: Connected redis.Redis instance for Tier 2 cache.
        is_template_fallback: When True, this flow was produced by the deterministic
            template path (not the LLM). Grading would not produce a meaningful
            quality signal; returns None so the caller skips DB writes entirely.
        threshold: Combined score below which Tier 3 escalation fires (default 60).
        sonnet_band_low: Lower bound of Haiku ambiguous band (default 40.0).
        sonnet_band_high: Upper bound of Haiku ambiguous band (default 60.0).

    Returns:
        GraderResult, or None when is_template_fallback=True.
    """
    if is_template_fallback:
        logger.debug("grader_skip_template_fallback", extra={"flow_id": flow_id})
        return None

    t1 = grade_tier1(blocks, game_data)
    t2_haiku = grade_tier2_cached(flow_id, blocks, game_data, redis_client)

    # Sonnet escalation: only when Haiku is uncertain (in the ambiguous band).
    t2_sonnet: TierTwoResult | None = None
    haiku_ambiguous = sonnet_band_low <= t2_haiku.score <= sonnet_band_high
    if haiku_ambiguous:
        logger.info(
            "grader_sonnet_escalation",
            extra={
                "flow_id": flow_id,
                "haiku_score": t2_haiku.score,
                "band_low": sonnet_band_low,
                "band_high": sonnet_band_high,
            },
        )
        t2_sonnet = grade_tier2_sonnet_cached(flow_id, blocks, game_data, redis_client)

    # Combined score uses Sonnet when available (more accurate for ambiguous cases).
    effective_t2 = t2_sonnet if t2_sonnet is not None else t2_haiku
    combined = compute_combined_score(t1, effective_t2)

    return GraderResult(
        flow_id=flow_id,
        sport=sport,
        tier1=t1,
        tier2=t2_haiku,
        combined_score=combined,
        escalated=combined < threshold,
        tier2_sonnet=t2_sonnet,
        haiku_ambiguous=haiku_ambiguous,
    )
