"""Tests for the model odds decision engine and Kelly sizing.

Phase 4 of the model odds pipeline.
"""

from __future__ import annotations

import pytest

from app.analytics.calibration.uncertainty import UncertaintyResult
from app.services.model_odds import (
    ModelOddsDecision,
    _classify_decision,
    _kelly_criterion,
    _price_beats_threshold,
    compute_model_odds,
)


# ---------------------------------------------------------------------------
# Kelly criterion tests
# ---------------------------------------------------------------------------


class TestKellyCriterion:
    """Test Kelly fraction computation."""

    def test_positive_edge_returns_positive_kelly(self):
        kelly = _kelly_criterion(0.55, 100.0)
        assert kelly > 0
        assert kelly < 0.15

    def test_no_edge_returns_zero(self):
        kelly = _kelly_criterion(0.50, 100.0)
        assert kelly == 0.0

    def test_negative_edge_returns_zero(self):
        kelly = _kelly_criterion(0.45, -110.0)
        assert kelly == 0.0

    def test_strong_favorite_at_plus_money(self):
        kelly = _kelly_criterion(0.60, 110.0)
        assert kelly > 0.05

    def test_invalid_price_returns_zero(self):
        kelly = _kelly_criterion(0.55, 0.0)
        assert kelly == 0.0

    def test_favorite_price_negative(self):
        kelly = _kelly_criterion(0.65, -150.0)
        assert kelly > 0

    def test_underdog_price_positive(self):
        kelly = _kelly_criterion(0.40, 200.0)
        assert abs(kelly - 0.10) < 0.01


# ---------------------------------------------------------------------------
# Decision classification tests
# ---------------------------------------------------------------------------


class TestClassifyDecision:

    def test_no_market_returns_no_play(self):
        result = _classify_decision(
            p_conservative=0.55, p_market=None, market_price=None,
            target_bet_line=110.0, confidence_tier="high",
        )
        assert result == "no_play"

    def test_very_low_confidence_always_no_play(self):
        result = _classify_decision(
            p_conservative=0.55, p_market=0.45, market_price=120.0,
            target_bet_line=110.0, confidence_tier="very_low",
        )
        assert result == "no_play"

    def test_no_edge_returns_no_play(self):
        result = _classify_decision(
            p_conservative=0.48, p_market=0.52, market_price=-110.0,
            target_bet_line=110.0, confidence_tier="high",
        )
        assert result == "no_play"

    def test_edge_exists_but_below_target_returns_lean(self):
        result = _classify_decision(
            p_conservative=0.54, p_market=0.52, market_price=-110.0,
            target_bet_line=-105.0, confidence_tier="medium",
        )
        assert result == "lean"

    def test_beats_target_returns_playable(self):
        result = _classify_decision(
            p_conservative=0.55, p_market=0.48, market_price=110.0,
            target_bet_line=105.0, confidence_tier="medium",
        )
        assert result == "playable"

    def test_strong_play_requires_high_confidence_and_big_edge(self):
        result = _classify_decision(
            p_conservative=0.60, p_market=0.48, market_price=110.0,
            target_bet_line=100.0, confidence_tier="high",
        )
        assert result == "strong_play"


# ---------------------------------------------------------------------------
# Price comparison helper
# ---------------------------------------------------------------------------


class TestPriceBeatsThreshold:

    def test_less_negative_beats_more_negative(self):
        assert _price_beats_threshold(-110.0, -150.0, is_favorite=True)

    def test_more_positive_beats_less_positive(self):
        assert _price_beats_threshold(130.0, 110.0, is_favorite=False)

    def test_same_price_does_not_beat(self):
        assert not _price_beats_threshold(-110.0, -110.0, is_favorite=True)


# ---------------------------------------------------------------------------
# Full compute_model_odds integration
# ---------------------------------------------------------------------------


class TestComputeModelOdds:

    def _make_uncertainty(self, tier: str = "medium") -> UncertaintyResult:
        from app.analytics.calibration.uncertainty import TIER_PENALTIES
        return UncertaintyResult(
            penalty=TIER_PENALTIES[tier], confidence_tier=tier,
            factors={"sim_variance": 0.1, "profile_freshness": 0.1,
                     "market_disagreement": 0.1, "pitcher_data": 0.0},
        )

    def test_returns_model_odds_decision(self):
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=None, uncertainty=self._make_uncertainty(),
        )
        assert isinstance(result, ModelOddsDecision)

    def test_favorite_line_is_negative(self):
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=None, uncertainty=self._make_uncertainty(),
        )
        assert result.fair_line_mid < 0
        assert result.p_true == 0.55

    def test_underdog_line_is_positive(self):
        result = compute_model_odds(
            calibrated_wp=0.45, market_price=None, uncertainty=self._make_uncertainty(),
        )
        assert result.fair_line_mid > 0

    def test_conservative_less_extreme_than_true(self):
        result = compute_model_odds(
            calibrated_wp=0.60, market_price=None, uncertainty=self._make_uncertainty(),
        )
        assert result.fair_line_conservative > result.fair_line_mid

    def test_kelly_positive_with_edge(self):
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=110.0, uncertainty=self._make_uncertainty("high"),
        )
        assert result.kelly_fraction > 0
        assert result.half_kelly > 0
        assert result.quarter_kelly > 0

    def test_kelly_zero_without_market(self):
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=None, uncertainty=self._make_uncertainty(),
        )
        assert result.kelly_fraction == 0.0

    def test_edge_vs_market_computed(self):
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=-110.0, uncertainty=self._make_uncertainty(),
        )
        assert result.edge_vs_market is not None

    def test_no_market_returns_no_play(self):
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=None, uncertainty=self._make_uncertainty(),
        )
        assert result.decision == "no_play"

    def test_strong_edge_with_high_confidence(self):
        result = compute_model_odds(
            calibrated_wp=0.60, market_price=120.0, uncertainty=self._make_uncertainty("high"),
        )
        assert result.decision in ("playable", "strong_play")

    def test_fifty_fifty_game(self):
        result = compute_model_odds(
            calibrated_wp=0.50, market_price=-110.0, uncertainty=self._make_uncertainty(),
        )
        assert result.p_conservative == 0.50
        assert result.decision == "no_play"

    def test_target_and_strong_lines_present(self):
        """Target and strong lines should be non-zero. Strong is at least as
        generous as target (higher American odds = better for bettor).
        They may be equal when both clamp to the 0.501/0.499 boundary."""
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=100.0, uncertainty=self._make_uncertainty(),
        )
        assert result.target_bet_line != 0.0
        assert result.strong_bet_line != 0.0
        assert result.strong_bet_line >= result.target_bet_line

    def test_required_edge_includes_friction(self):
        from app.analytics.calibration.uncertainty import TAX_FRICTION_BUFFER, TIER_REQUIRED_EDGE
        result = compute_model_odds(
            calibrated_wp=0.55, market_price=100.0, uncertainty=self._make_uncertainty("medium"),
        )
        expected = TIER_REQUIRED_EDGE["medium"] + TAX_FRICTION_BUFFER
        assert abs(result.required_edge - expected) < 0.001

    def test_underdog_with_market_target_lines_positive(self):
        """Underdog side (p < 0.5): target and strong lines should be
        positive American odds. Strong requires more edge → higher
        probability threshold → LOWER positive American number (closer
        to even money). The book must offer MORE than the threshold."""
        result = compute_model_odds(
            calibrated_wp=0.42, market_price=160.0,
            uncertainty=self._make_uncertainty("medium"),
        )
        # Both lines should be positive (underdog territory)
        assert result.target_bet_line > 0
        assert result.strong_bet_line > 0
        # Strong threshold is tighter (lower American number = higher
        # implied probability), so the book must offer even more than this
        assert result.strong_bet_line <= result.target_bet_line

    def test_underdog_higher_uncertainty_widens_target(self):
        """Higher uncertainty → larger required edge → target probability
        pushed closer to 0.5 → lower positive American odds (tighter
        threshold the book must exceed)."""
        result_high = compute_model_odds(
            calibrated_wp=0.42, market_price=160.0,
            uncertainty=self._make_uncertainty("high"),
        )
        result_low = compute_model_odds(
            calibrated_wp=0.42, market_price=160.0,
            uncertainty=self._make_uncertainty("low"),
        )
        # Low confidence → larger edge → target probability closer to 0.5
        # → lower positive American odds (tighter threshold)
        assert result_low.target_bet_line <= result_high.target_bet_line
