"""Unit tests for the 3-tier narrative quality grader (ISSUE-045).

Coverage:
- Tier 1 rule-based check failures (block count, word length, forbidden phrases,
  score consistency, team name consistency)
- Tier 2 Redis cache hit vs miss
- Escalation boundary conditions (above/at/below threshold)
- Template-fallback no-op path
- Combined score formula
"""

from __future__ import annotations

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _mock_anthropic_module() -> MagicMock:
    """Return a minimal mock of the anthropic package for test environments."""
    mod = MagicMock()
    mod.Anthropic = MagicMock()
    return mod

from sports_scraper.pipeline.grader import (
    ESCALATION_THRESHOLD,
    MAX_BLOCKS,
    MAX_TOTAL_WORDS,
    MAX_WORDS_PER_BLOCK,
    MIN_BLOCKS,
    MIN_WORDS_PER_BLOCK,
    SONNET_AMBIGUOUS_BAND_HIGH,
    SONNET_AMBIGUOUS_BAND_LOW,
    GraderResult,
    TierOneResult,
    TierTwoResult,
    compute_combined_score,
    grade_flow,
    grade_tier1,
    grade_tier2_cached,
    grade_tier2_sonnet_cached,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_GOOD_NARRATIVE = (
    "The Lakers opened with a 10-5 run behind strong defense and sharp shooting "
    "from the perimeter, setting the tone for the rest of the game."
)


def _make_blocks(
    narratives: list[str] | None = None,
    n: int = 3,
) -> list[dict]:
    """Build minimal valid block dicts."""
    if narratives is None:
        narratives = [_GOOD_NARRATIVE] * n
    return [
        {
            "block_index": i,
            "role": "SETUP" if i == 0 else "RESOLUTION",
            "narrative": narratives[i],
            "score_before": [0, 0],
            "score_after": [10, 5],
            "moment_indices": [i],
            "play_ids": [i + 1],
        }
        for i in range(len(narratives))
    ]


def _game_data(
    home_team: str = "Lakers",
    away_team: str = "Celtics",
    home_score: int = 10,
    away_score: int = 5,
    sport: str = "NBA",
) -> dict:
    return {
        "sport": sport,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
    }


# ── Tier 1: block count ───────────────────────────────────────────────────────


class TestTier1BlockCount:
    def test_too_few_blocks(self):
        blocks = _make_blocks(n=MIN_BLOCKS - 1)
        result = grade_tier1(blocks, _game_data())
        assert result.checks["block_count"] is False
        assert any("block_count" in f for f in result.failures)
        assert result.score < 100

    def test_too_many_blocks(self):
        blocks = _make_blocks(n=MAX_BLOCKS + 1)
        result = grade_tier1(blocks, _game_data())
        assert result.checks["block_count"] is False

    def test_valid_block_count(self):
        blocks = _make_blocks(n=MIN_BLOCKS)
        result = grade_tier1(blocks, _game_data())
        assert result.checks["block_count"] is True

    def test_max_valid_block_count(self):
        blocks = _make_blocks(n=MAX_BLOCKS)
        result = grade_tier1(blocks, _game_data())
        assert result.checks["block_count"] is True


# ── Tier 1: word length ───────────────────────────────────────────────────────


class TestTier1WordLength:
    def test_block_too_short(self):
        short = "Too short."
        blocks = _make_blocks(narratives=[_GOOD_NARRATIVE, _GOOD_NARRATIVE, short])
        result = grade_tier1(blocks, _game_data())
        assert result.checks["block_word_lengths"] is False
        assert any("too short" in f for f in result.failures)

    def test_block_too_long(self):
        long_text = " ".join(["word"] * (MAX_WORDS_PER_BLOCK + 1))
        blocks = _make_blocks(narratives=[_GOOD_NARRATIVE, _GOOD_NARRATIVE, long_text])
        result = grade_tier1(blocks, _game_data())
        assert result.checks["block_word_lengths"] is False
        assert any("too long" in f for f in result.failures)

    def test_total_words_exceeded(self):
        long_narrative = " ".join(["word"] * 100)  # 100 words × 7 blocks = 700 > 600
        blocks = _make_blocks(narratives=[long_narrative] * MAX_BLOCKS)
        result = grade_tier1(blocks, _game_data())
        assert result.checks["total_words"] is False
        assert any("total_words" in f for f in result.failures)


# ── Tier 1: forbidden phrases ─────────────────────────────────────────────────


class TestTier1ForbiddenPhrases:
    def test_detects_ai_artifact(self):
        bad = _GOOD_NARRATIVE + " As an AI language model, I cannot provide further details."
        blocks = _make_blocks(narratives=[_GOOD_NARRATIVE, _GOOD_NARRATIVE, bad])
        result = grade_tier1(blocks, _game_data())
        assert result.checks["forbidden_phrases"] is False
        assert any("forbidden_phrases" in f for f in result.failures)

    def test_detects_in_conclusion(self):
        bad = _GOOD_NARRATIVE + " In conclusion, the Lakers won."
        blocks = _make_blocks(narratives=[_GOOD_NARRATIVE, bad, _GOOD_NARRATIVE])
        result = grade_tier1(blocks, _game_data())
        assert result.checks["forbidden_phrases"] is False

    def test_clean_narrative_no_forbidden(self):
        blocks = _make_blocks(n=3)
        result = grade_tier1(blocks, _game_data())
        assert result.checks["forbidden_phrases"] is True

    def test_case_insensitive(self):
        bad = _GOOD_NARRATIVE + " AS AN AI I cannot help."
        blocks = _make_blocks(narratives=[_GOOD_NARRATIVE, _GOOD_NARRATIVE, bad])
        result = grade_tier1(blocks, _game_data())
        assert result.checks["forbidden_phrases"] is False


# ── Tier 1: score and team name consistency ───────────────────────────────────


class TestTier1ScoreConsistency:
    def test_score_mentioned(self):
        narrative = "The Lakers defeated the Celtics 10-5 in a dominant display."
        blocks = _make_blocks(narratives=[narrative, narrative, narrative])
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert result.checks["score_consistency"] is True

    def test_score_not_mentioned(self):
        # Narrative has no score reference matching 10-5 or 5-10
        narrative = "The Lakers played well against the Celtics in a competitive match."
        blocks = _make_blocks(narratives=[narrative, narrative, narrative])
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert result.checks["score_consistency"] is False
        assert any("score_not_mentioned" in f for f in result.failures)

    def test_score_check_skipped_when_scores_unknown(self):
        blocks = _make_blocks(n=3)
        gd = _game_data()
        gd["home_score"] = None
        gd["away_score"] = None
        result = grade_tier1(blocks, gd)
        assert result.checks["score_consistency"] is True

    def test_team_name_missing(self):
        narrative = "The home team won convincingly tonight in a great performance."
        blocks = _make_blocks(narratives=[narrative, narrative, narrative])
        result = grade_tier1(blocks, _game_data(home_team="Lakers", away_team="Celtics"))
        assert result.checks["team_name_consistency"] is False
        assert any("team_names_missing" in f for f in result.failures)

    def test_team_name_check_skipped_when_no_teams(self):
        blocks = _make_blocks(n=3)
        gd = _game_data(home_team="", away_team="")
        result = grade_tier1(blocks, gd)
        assert result.checks["team_name_consistency"] is True


# ── Tier 1: perfect flow ──────────────────────────────────────────────────────


class TestTier1PerfectFlow:
    def test_all_checks_pass_gives_100(self):
        # 35+ words per block — comfortably above MIN_WORDS_PER_BLOCK (30)
        narrative = (
            "The Lakers opened with a commanding 10-5 lead over the Celtics showcasing "
            "their depth in the paint and perimeter shooting from multiple contributors "
            "as Anthony Davis scored early and LeBron James facilitated beautifully tonight."
        )
        blocks = _make_blocks(narratives=[narrative, narrative, narrative])
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert result.score == 100.0
        assert result.failures == []
        assert all(result.checks.values())


# ── Tier 2: cache hit / miss ──────────────────────────────────────────────────


class TestTier2CacheHitMiss:
    def _make_redis(self, cached_value: str | None) -> MagicMock:
        r = MagicMock()
        r.get.return_value = cached_value
        return r

    def test_cache_hit_returns_cached_score(self):
        cached_data = json.dumps(
            {
                "score": 78.0,
                "rubric": {
                    "factual_accuracy": 20,
                    "sport_specific_voice": 20,
                    "narrative_coherence": 19,
                    "no_generic_filler": 19,
                },
            }
        )
        redis = self._make_redis(cached_data)
        blocks = _make_blocks(n=3)
        result = grade_tier2_cached(
            flow_id=1, blocks=blocks, game_data=_game_data(), redis_client=redis
        )
        assert result.cache_hit is True
        assert result.score == 78.0
        redis.setex.assert_not_called()

    def test_cache_miss_calls_llm_and_caches_result(self):
        redis = self._make_redis(None)
        blocks = _make_blocks(n=3)
        mock_content = MagicMock()
        mock_content.text = json.dumps(
            {
                "factual_accuracy": 22,
                "sport_specific_voice": 20,
                "narrative_coherence": 18,
                "no_generic_filler": 21,
                "reasoning": "Good recap.",
            }
        )
        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthro_mod = MagicMock()
        mock_anthro_mod.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthro_mod}):
            result = grade_tier2_cached(
                flow_id=2, blocks=blocks, game_data=_game_data(), redis_client=redis
            )

        assert result.cache_hit is False
        assert result.score == 81.0  # 22+20+18+21
        assert "factual_accuracy" in result.rubric
        redis.setex.assert_called_once()

    def test_cache_miss_llm_failure_returns_neutral_50(self):
        redis = self._make_redis(None)
        blocks = _make_blocks(n=3)

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API down")
        mock_anthro_mod = MagicMock()
        mock_anthro_mod.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthro_mod}):
            result = grade_tier2_cached(
                flow_id=3, blocks=blocks, game_data=_game_data(), redis_client=redis
            )

        assert result.cache_hit is False
        assert result.score == 50.0
        assert result.rubric == {}

    def test_corrupted_cache_falls_through_to_llm(self):
        redis = self._make_redis("not-valid-json{{")
        blocks = _make_blocks(n=3)
        mock_content = MagicMock()
        mock_content.text = json.dumps(
            {"factual_accuracy": 20, "sport_specific_voice": 20, "narrative_coherence": 20, "no_generic_filler": 20}
        )
        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthro_mod = MagicMock()
        mock_anthro_mod.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthro_mod}):
            result = grade_tier2_cached(
                flow_id=4, blocks=blocks, game_data=_game_data(), redis_client=redis
            )

        assert result.cache_hit is False
        assert result.score == 80.0


# ── Combined score formula ────────────────────────────────────────────────────


class TestComputeCombinedScore:
    def test_tier2_available_uses_weighted_formula(self):
        t1 = TierOneResult(score=80.0)
        t2 = TierTwoResult(score=60.0)
        # 0.4 * 80 + 0.6 * 60 = 32 + 36 = 68
        assert compute_combined_score(t1, t2) == 68.0

    def test_tier2_none_returns_tier1_score(self):
        t1 = TierOneResult(score=75.0)
        assert compute_combined_score(t1, None) == 75.0

    def test_both_100_gives_100(self):
        t1 = TierOneResult(score=100.0)
        t2 = TierTwoResult(score=100.0)
        assert compute_combined_score(t1, t2) == 100.0

    def test_both_0_gives_0(self):
        t1 = TierOneResult(score=0.0)
        t2 = TierTwoResult(score=0.0)
        assert compute_combined_score(t1, t2) == 0.0


# ── Escalation boundary conditions ───────────────────────────────────────────


class TestEscalationBoundary:
    def _grade(self, combined: float, threshold: float = ESCALATION_THRESHOLD) -> bool:
        """Simulate escalation decision for a given combined score."""
        from sports_scraper.pipeline.grader import GraderResult

        t1 = TierOneResult(score=100.0)
        t2 = TierTwoResult(score=(combined - 40) / 0.6)  # back-calculate
        result = GraderResult(
            flow_id=1,
            sport="NBA",
            tier1=t1,
            tier2=t2,
            combined_score=combined,
            escalated=combined < threshold,
        )
        return result.escalated

    def test_score_below_threshold_escalates(self):
        assert self._grade(ESCALATION_THRESHOLD - 1) is True

    def test_score_at_threshold_does_not_escalate(self):
        assert self._grade(ESCALATION_THRESHOLD) is False

    def test_score_above_threshold_does_not_escalate(self):
        assert self._grade(ESCALATION_THRESHOLD + 1) is False

    def test_custom_threshold(self):
        t1 = TierOneResult(score=75.0)
        redis = MagicMock()
        redis.get.return_value = json.dumps({"score": 75.0, "rubric": {}})
        blocks = _make_blocks(n=3)

        result = grade_flow(
            flow_id=99,
            sport="NFL",
            blocks=blocks,
            game_data=_game_data(),
            redis_client=redis,
            threshold=80.0,  # higher threshold
        )
        assert result is not None
        # combined will be well below 80 if tier2 also returns 75
        # (0.4*t1 + 0.6*t2) where both are ~75 → 75, which is < 80
        assert result.escalated is True


# ── Template fallback no-op ───────────────────────────────────────────────────


class TestTemplateFallbackNoOp:
    def test_template_fallback_returns_none(self):
        redis = MagicMock()
        blocks = _make_blocks(n=3)
        result = grade_flow(
            flow_id=1,
            sport="NBA",
            blocks=blocks,
            game_data=_game_data(),
            redis_client=redis,
            is_template_fallback=True,
        )
        assert result is None
        redis.get.assert_not_called()
        redis.setex.assert_not_called()

    def test_non_template_flow_returns_grader_result(self):
        redis = MagicMock()
        redis.get.return_value = json.dumps({"score": 85.0, "rubric": {}})
        blocks = _make_blocks(n=3)
        result = grade_flow(
            flow_id=2,
            sport="NBA",
            blocks=blocks,
            game_data=_game_data(),
            redis_client=redis,
            is_template_fallback=False,
        )
        assert isinstance(result, GraderResult)
        assert result.flow_id == 2


# ── Generic phrase detection ──────────────────────────────────────────────────


class TestGenericPhraseDetection:
    """Tests for per-block generic phrase scoring in the tier-1 grader."""

    # Build a narrative that is long enough, mentions teams + score, and has
    # no forbidden phrases so only the generic-phrase penalty affects the score.
    _CLEAN = (
        "The Lakers opened with a commanding 10-5 lead over the Celtics showcasing "
        "their depth in the paint and perimeter shooting from multiple contributors "
        "as Anthony Davis scored early and LeBron James facilitated beautifully tonight."
    )
    _WITH_CLICHES = (
        "The Lakers gave it their all and played their hearts out, showing a lot of "
        "heart as the Celtics gave it their all but the Lakers proved too much. "
        "It was a hard-fought battle and the rest is history with the final score 10-5."
    )

    def test_clean_flow_higher_score_than_generic_flow(self) -> None:
        """Flow with 0 generic phrases must score higher than one with 5+ matches."""
        clean_blocks = _make_blocks(narratives=[self._CLEAN, self._CLEAN, self._CLEAN])
        generic_blocks = _make_blocks(
            narratives=[self._WITH_CLICHES, self._WITH_CLICHES, self._WITH_CLICHES]
        )
        clean_result = grade_tier1(clean_blocks, _game_data())
        generic_result = grade_tier1(generic_blocks, _game_data(home_score=10, away_score=5))
        assert clean_result.score > generic_result.score

    def test_generic_phrases_appear_in_failures(self) -> None:
        """Matched generic phrases are recorded in TierOneResult.failures."""
        blocks = _make_blocks(narratives=[self._WITH_CLICHES, self._WITH_CLICHES, self._WITH_CLICHES])
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert any("generic_phrase_matches" in f for f in result.failures)

    def test_no_generic_phrases_no_penalty(self) -> None:
        """A flow with zero generic phrase matches carries no penalty."""
        from sports_scraper.pipeline.grader_rules.generic_phrases import GENERIC_PHRASES

        # Make a clean narrative containing none of the loaded phrases
        clean = (
            "The Lakers dominated the fourth quarter with Anthony Davis recording "
            "eight consecutive points while LeBron James distributed the ball "
            "effectively for a final score of 10-5 over the Celtics tonight."
        )
        # Verify our narrative doesn't accidentally contain any phrase
        lower = clean.lower()
        assert not any(p in lower for p in GENERIC_PHRASES), (
            "Test narrative inadvertently contains a generic phrase — update it."
        )
        blocks = _make_blocks(narratives=[clean, clean, clean])
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert not any("generic_phrase_matches" in f for f in result.failures)

    def test_detection_is_case_insensitive(self) -> None:
        """Detection must match regardless of casing ('GAVE IT THEIR ALL' == 'gave it their all')."""
        upper_cliche = self._CLEAN + " The team GAVE IT THEIR ALL and showed HEART."
        blocks = _make_blocks(narratives=[upper_cliche, self._CLEAN, self._CLEAN])
        result = grade_tier1(blocks, _game_data())
        assert any("generic_phrase_matches" in f for f in result.failures)

    def test_detection_across_sentence_boundary(self) -> None:
        """Phrase spanning multiple sentences is still a substring of the block text."""
        # Insert a phrase that bridges punctuation (it's a substring match, so no boundary issue)
        narrative = (
            "The Lakers scored quickly. Gave it their all. "
            "The Celtics could not respond in the final 10-5 result."
        )
        blocks = _make_blocks(narratives=[narrative, self._CLEAN, self._CLEAN])
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert any("generic_phrase_matches" in f for f in result.failures)

    def test_penalty_scales_with_match_count(self) -> None:
        """More generic phrase matches → lower score (linear penalty)."""
        from sports_scraper.pipeline.grader_rules.generic_phrases import GENERIC_PHRASE_WEIGHT

        one_match = (
            "The Lakers gave it their all tonight and won 10-5 over the Celtics "
            "with strong contributions from every player on the roster here."
        )
        five_matches = (
            "The Lakers gave it their all, played their hearts out, and proved too much "
            "in a hard-fought battle showing they made their mark. They won 10-5 over "
            "the Celtics from start to finish in a dominant display tonight."
        )
        blocks_one = _make_blocks(narratives=[one_match, one_match, one_match])
        blocks_five = _make_blocks(narratives=[five_matches, five_matches, five_matches])
        result_one = grade_tier1(blocks_one, _game_data(home_score=10, away_score=5))
        result_five = grade_tier1(blocks_five, _game_data(home_score=10, away_score=5))
        assert result_one.score > result_five.score


# ── Generic phrases module ────────────────────────────────────────────────────


class TestGenericPhrasesModule:
    """Tests for the grader_rules.generic_phrases module itself."""

    def test_phrase_list_has_30_or_more_entries(self) -> None:
        from sports_scraper.pipeline.grader_rules.generic_phrases import GENERIC_PHRASES

        assert len(GENERIC_PHRASES) >= 30, (
            f"Expected ≥30 phrases, got {len(GENERIC_PHRASES)}. "
            "Add more entries to generic_phrases.toml."
        )

    def test_all_phrases_are_lowercase(self) -> None:
        from sports_scraper.pipeline.grader_rules.generic_phrases import GENERIC_PHRASES

        for phrase in GENERIC_PHRASES:
            assert phrase == phrase.lower(), f"Phrase not lowercased: {phrase!r}"

    def test_detect_per_block_returns_matches(self) -> None:
        from sports_scraper.pipeline.grader_rules.generic_phrases import detect_per_block

        text = "The team gave it their all and made their mark tonight."
        matches = detect_per_block(text)
        assert "gave it their all" in matches
        assert "made their mark" in matches

    def test_detect_per_block_empty_text(self) -> None:
        from sports_scraper.pipeline.grader_rules.generic_phrases import detect_per_block

        assert detect_per_block("") == []

    def test_phrase_density_zero_for_clean_text(self) -> None:
        from sports_scraper.pipeline.grader_rules.generic_phrases import phrase_density

        clean = (
            "Anthony Davis scored 28 points with 12 rebounds in the fourth quarter "
            "while LeBron James recorded his tenth triple-double of the season."
        )
        assert phrase_density(clean) == 0.0

    def test_phrase_density_calculation(self) -> None:
        from sports_scraper.pipeline.grader_rules.generic_phrases import phrase_density

        # One phrase in 10 words = 10.0 per 100
        text = "They gave it their all over the course of tonight."
        density = phrase_density(text)
        assert density > 0.0


# ── Tier 1: resolution_specificity ───────────────────────────────────────────


class TestTier1ResolutionSpecificity:
    """Tests for the resolution_specificity named dimension in grade_tier1."""

    _NARRATIVE = (
        "The Lakers opened with a 10-5 run behind strong defense and sharp shooting "
        "from the perimeter, setting the tone for the rest of the game. "
        "They defeated the Celtics 10-5."
    )

    def _blocks_with_flag(self, flag: bool) -> list[dict]:
        """Build blocks where the RESOLUTION block carries (or not) the specificity flag."""
        return [
            {
                "block_index": 0,
                "role": "SETUP",
                "narrative": self._NARRATIVE,
                "resolution_specificity_warning": False,
            },
            {
                "block_index": 1,
                "role": "RESOLUTION",
                "narrative": self._NARRATIVE,
                "resolution_specificity_warning": flag,
            },
        ]

    def test_no_warning_flag_passes_check(self) -> None:
        """RESOLUTION block without the flag has resolution_specificity=True."""
        blocks = self._blocks_with_flag(False)
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert result.checks.get("resolution_specificity") is True
        assert not any("resolution_specificity" in f for f in result.failures)

    def test_warning_flag_fails_check(self) -> None:
        """RESOLUTION block with the flag has resolution_specificity=False and a failure."""
        blocks = self._blocks_with_flag(True)
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert result.checks.get("resolution_specificity") is False
        assert any("resolution_specificity" in f for f in result.failures)

    def test_no_resolution_block_skips_check(self) -> None:
        """When no RESOLUTION block exists the check is absent from the checks dict."""
        blocks = [
            {"block_index": 0, "role": "SETUP", "narrative": self._NARRATIVE},
            {"block_index": 1, "role": "RESPONSE", "narrative": self._NARRATIVE},
        ]
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert "resolution_specificity" not in result.checks

    def test_check_appears_as_named_dimension(self) -> None:
        """resolution_specificity is a named key in checks (not buried in generic log)."""
        blocks = self._blocks_with_flag(False)
        result = grade_tier1(blocks, _game_data(home_score=10, away_score=5))
        assert "resolution_specificity" in result.checks

    def test_flagged_resolution_lowers_score(self) -> None:
        """A flow with the specificity flag set must score lower than one without."""
        clean_blocks = self._blocks_with_flag(False)
        flagged_blocks = self._blocks_with_flag(True)
        clean_result = grade_tier1(clean_blocks, _game_data(home_score=10, away_score=5))
        flagged_result = grade_tier1(flagged_blocks, _game_data(home_score=10, away_score=5))
        assert clean_result.score > flagged_result.score


# ── Sonnet escalation path ────────────────────────────────────────────────────


def _make_redis_cached(score: float, rubric: dict | None = None) -> MagicMock:
    """Return a Redis mock that serves a cached tier2 result."""
    r = MagicMock()
    r.get.return_value = json.dumps({"score": score, "rubric": rubric or {}})
    return r


def _make_llm_mock(dims: dict) -> tuple[MagicMock, MagicMock]:
    """Return (mock_content, mock_anthropic_module) for an LLM response."""
    content = MagicMock()
    content.text = json.dumps({**dims, "reasoning": "test"})
    msg = MagicMock()
    msg.content = [content]
    client = MagicMock()
    client.messages.create.return_value = msg
    mod = MagicMock()
    mod.Anthropic.return_value = client
    return client, mod


class TestSonnetAmbiguousPath:
    """Sonnet is invoked iff Haiku score is in the ambiguous band."""

    def test_haiku_below_band_skips_sonnet(self):
        """Haiku score below the band → fail fast, no Sonnet call."""
        haiku_score = SONNET_AMBIGUOUS_BAND_LOW - 1  # clearly bad
        redis = _make_redis_cached(haiku_score)
        blocks = _make_blocks(n=3)

        result = grade_flow(
            flow_id=1,
            sport="NBA",
            blocks=blocks,
            game_data=_game_data(),
            redis_client=redis,
        )
        assert result is not None
        assert result.tier2_sonnet is None
        assert result.haiku_ambiguous is False

    def test_haiku_above_band_skips_sonnet(self):
        """Haiku score above the band → pass fast, no Sonnet call."""
        haiku_score = SONNET_AMBIGUOUS_BAND_HIGH + 1  # clearly good
        redis = _make_redis_cached(haiku_score)
        blocks = _make_blocks(n=3)

        result = grade_flow(
            flow_id=2,
            sport="NBA",
            blocks=blocks,
            game_data=_game_data(),
            redis_client=redis,
        )
        assert result is not None
        assert result.tier2_sonnet is None
        assert result.haiku_ambiguous is False

    def test_haiku_in_band_invokes_sonnet(self):
        """Haiku score in [LOW, HIGH] → Sonnet is called."""
        haiku_score = (SONNET_AMBIGUOUS_BAND_LOW + SONNET_AMBIGUOUS_BAND_HIGH) / 2
        redis = MagicMock()
        # Haiku cache hit, Sonnet cache miss → LLM call
        sonnet_dims = {
            "factual_accuracy": 20,
            "sport_specific_voice": 18,
            "narrative_coherence": 19,
            "no_generic_filler": 17,
        }

        def redis_get(key: str):
            if key.startswith("grader:t2:"):
                return json.dumps({"score": haiku_score, "rubric": {}})
            return None  # Sonnet cache miss

        redis.get.side_effect = redis_get

        _, mock_anthro = _make_llm_mock(sonnet_dims)
        blocks = _make_blocks(n=3)

        with patch.dict(sys.modules, {"anthropic": mock_anthro}):
            result = grade_flow(
                flow_id=3,
                sport="NBA",
                blocks=blocks,
                game_data=_game_data(),
                redis_client=redis,
            )

        assert result is not None
        assert result.haiku_ambiguous is True
        assert result.tier2_sonnet is not None
        assert result.tier2_sonnet.score == sum(sonnet_dims.values())

    def test_haiku_ambiguous_combined_score_uses_sonnet(self):
        """When Haiku is ambiguous, combined score is T1 + Sonnet (not Haiku)."""
        haiku_score = 50.0  # ambiguous
        sonnet_score = 80.0  # clearly good — would publish

        redis = MagicMock()

        def redis_get(key: str):
            if key.startswith("grader:t2:"):
                return json.dumps({"score": haiku_score, "rubric": {}})
            if key.startswith("grader:t2s:"):
                return json.dumps({"score": sonnet_score, "rubric": {}})
            return None

        redis.get.side_effect = redis_get
        blocks = _make_blocks(n=3)

        result = grade_flow(
            flow_id=4,
            sport="NBA",
            blocks=blocks,
            game_data=_game_data(),
            redis_client=redis,
        )
        assert result is not None
        assert result.haiku_ambiguous is True
        # Combined score: T1 * 0.4 + Sonnet * 0.6 (NOT Haiku)
        from sports_scraper.pipeline.grader import _TIER1_WEIGHT, _TIER2_WEIGHT

        expected = round(_TIER1_WEIGHT * result.tier1.score + _TIER2_WEIGHT * sonnet_score, 1)
        assert result.combined_score == expected

    def test_haiku_at_band_boundaries_treated_as_ambiguous(self):
        """Boundary values (exactly LOW or HIGH) are inclusive → Sonnet is invoked."""
        for boundary in (SONNET_AMBIGUOUS_BAND_LOW, SONNET_AMBIGUOUS_BAND_HIGH):
            redis = MagicMock()
            redis.get.return_value = json.dumps({"score": boundary, "rubric": {}})
            blocks = _make_blocks(n=3)

            result = grade_flow(
                flow_id=5,
                sport="NBA",
                blocks=blocks,
                game_data=_game_data(),
                redis_client=redis,
            )
            assert result is not None
            assert result.haiku_ambiguous is True, f"Expected ambiguous at score={boundary}"

    def test_sonnet_cache_hit_skips_llm_call(self):
        """When both Haiku and Sonnet have cache hits, no LLM calls are made."""
        haiku_score = 50.0
        sonnet_score = 75.0

        redis = MagicMock()

        def redis_get(key: str):
            if key.startswith("grader:t2:"):
                return json.dumps({"score": haiku_score, "rubric": {}})
            if key.startswith("grader:t2s:"):
                return json.dumps({"score": sonnet_score, "rubric": {}})
            return None

        redis.get.side_effect = redis_get

        mock_client = MagicMock()
        mock_anthro = MagicMock()
        mock_anthro.Anthropic.return_value = mock_client
        blocks = _make_blocks(n=3)

        with patch.dict(sys.modules, {"anthropic": mock_anthro}):
            result = grade_tier2_sonnet_cached(
                flow_id=6, blocks=blocks, game_data=_game_data(), redis_client=redis
            )

        assert result.cache_hit is True
        assert result.score == sonnet_score
        mock_client.messages.create.assert_not_called()

    def test_sonnet_llm_failure_returns_neutral_50(self):
        """Sonnet LLM failure returns neutral 50 without blocking pipeline."""
        redis = MagicMock()
        redis.get.return_value = None  # cache miss

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("Sonnet API down")
        mock_anthro = MagicMock()
        mock_anthro.Anthropic.return_value = mock_client

        with patch.dict(sys.modules, {"anthropic": mock_anthro}):
            result = grade_tier2_sonnet_cached(
                flow_id=7,
                blocks=_make_blocks(n=3),
                game_data=_game_data(),
                redis_client=redis,
            )

        assert result.score == 50.0
        assert result.rubric == {}
        assert result.cache_hit is False
