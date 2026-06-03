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

import json
import logging
import re

import redis

from .grader_config import (
    _LLM_RUBRIC_PROMPT,
    _LLM_RUBRIC_SONNET_PROMPT,
    _TIER1_WEIGHT,
    _TIER2_WEIGHT,
    ESCALATION_THRESHOLD,
    FORBIDDEN_PHRASES,
    MAX_BLOCKS,
    MAX_TOTAL_WORDS,
    MAX_WORDS_PER_BLOCK,
    MIN_BLOCKS,
    MIN_WORDS_PER_BLOCK,
    SONNET_AMBIGUOUS_BAND_HIGH,
    SONNET_AMBIGUOUS_BAND_LOW,
    SONNET_MODEL,
    TIER2_CACHE_TTL,
)
from .grader_models import GraderResult, TierOneResult, TierTwoResult
from .grader_parsing import (
    _all_block_narratives,
    _compute_prompt_hash,
    _count_words,
    _parse_tier2_rubric_json,
    _strip_code_fence,
)
from .grader_rules.generic_phrases import (
    GENERIC_PHRASE_WEIGHT,
)
from .grader_rules.generic_phrases import (
    detect_per_block as _detect_generic_per_block,
)

logger = logging.getLogger(__name__)

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
    raw = ""
    # Split the SDK call from the response-parse so a bug in the parsing
    # block (NameError, AttributeError on a renamed field, etc.) is not
    # masked as an "LLM call failed". The outer catch stays broad because
    # `anthropic` may be a mock module in tests (test_grader.py patches
    # sys.modules and raises RuntimeError as `messages.create.side_effect`),
    # and `anthropic.APIError` on a MagicMock is not a real exception class.
    # See docs/audits/error-handling-report.md Appendix B.
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        logger.warning(
            "grader_t2_llm_call_failed",
            exc_info=True,
            extra={"flow_id": flow_id, "model": model},
        )
        # Neutral score on LLM failure; pipeline is not blocked
        score = 50.0
        rubric = {}
    else:
        try:
            raw = _strip_code_fence(message.content[0].text.strip())
            score, rubric = _parse_tier2_rubric_json(raw)
        except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError):
            logger.warning(
                "grader_t2_llm_parse_failed",
                exc_info=True,
                extra={
                    "flow_id": flow_id,
                    "model": model,
                    "raw_length": len(raw),
                },
            )
            score = 50.0
            rubric = {}

    result = TierTwoResult(score=score, rubric=rubric, cache_hit=False, model=model)
    try:
        redis_client.setex(  # type: ignore[union-attr]
            cache_key,
            TIER2_CACHE_TTL,
            json.dumps({"score": score, "rubric": rubric}),
        )
    except redis.RedisError:
        # Narrowed from `Exception` per docs/audits/error-handling-report.md Appendix B: a
        # cache-write failure is by definition a Redis client error; any
        # other exception (TypeError on json.dumps, etc.) should propagate
        # because it signals a programming bug rather than a transient
        # backing-store outage.
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
    raw = ""
    # See docs/audits/error-handling-report.md Appendix B: same split-catch rationale as the
    # Haiku path above. The SDK call stays broad (test stubs raise plain
    # RuntimeError), the response-parse is narrowed so a parsing bug
    # propagates instead of silently neutral-scoring.
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        logger.warning(
            "grader_t2s_llm_call_failed",
            exc_info=True,
            extra={"flow_id": flow_id, "model": SONNET_MODEL},
        )
        # Neutral score on LLM failure; pipeline is not blocked
        score = 50.0
        rubric = {}
    else:
        try:
            raw = _strip_code_fence(message.content[0].text.strip())
            score, rubric = _parse_tier2_rubric_json(raw)
        except (json.JSONDecodeError, ValueError, KeyError, IndexError, TypeError):
            logger.warning(
                "grader_t2s_llm_parse_failed",
                exc_info=True,
                extra={
                    "flow_id": flow_id,
                    "model": SONNET_MODEL,
                    "raw_length": len(raw),
                },
            )
            score = 50.0
            rubric = {}

    result = TierTwoResult(score=score, rubric=rubric, cache_hit=False, model=SONNET_MODEL)
    try:
        redis_client.setex(  # type: ignore[union-attr]
            cache_key,
            TIER2_CACHE_TTL,
            json.dumps({"score": score, "rubric": rubric}),
        )
    except redis.RedisError:
        # Narrowed from `Exception` per docs/audits/error-handling-report.md Appendix B:
        # same rationale as the Haiku cache-write block above.
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
