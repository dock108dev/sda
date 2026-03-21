"""Tests for the fair-odds decision engine and Kelly sizing.

Phase 4 of the fair-odds pipeline.
"""

from __future__ import annotations

import pytest

from app.analytics.calibration.uncertainty import UncertaintyResult
from app.services.fair_odds import (
    FairOddsDecision,
    _classify_decision,
    _kelly_criterion,
    _price_beats_threshold,
    compute_fair_odds,
)


# ---------------------------------------------------------------------------
# Kelly criterion tests
# ---------------------------------------------------------------------------


class TestKellyCriterion:
    """Test Kelly fraction computation."""

    def test_positive_edge_returns_positive_kelly(self):
        """Clear edge → positive Kelly fraction."""
        # p=0.55, price=+100 (even money): edge = 0.55-0.50 = 0.05
        kelly = _kelly_criterion(0.55, 100.0)
        assert kelly > 0
        assert kelly < 0.15

    def test_no_edge_returns_zero(self):
        """No edge → zero Kelly."""
        # p=0.50 at even money
        kelly = _kelly_criterion(0.50, 100.0)
        assert kelly == 0.0

    def test_negative_edge_returns_zero(self):
        """Negative edge → zero (no bet)."""
        # p=0.45 at -110 (implied ~52.4%)
        kelly = _kelly_criterion(0.45, -110.0)
        assert kelly == 0.0

    def test_strong_favorite_at_plus_money(self):
        """Strong favorite getting plus money = large Kelly."""
        kelly = _kelly_criterion(0.60, 110.0)
        assert kelly > 0.05

    def test_invalid_price_returns_zero(self):
        kelly = _kelly_criterion(0.55, 0.0)
        assert kelly == 0.0

    def test_favorite_price_negative(self):
        """Bet on favorite at -150."""
        # p=0.65, price=-150: b=100/150=0.667, kelly=(0.65*0.667-0.35)/0.667
        kelly = _kelly_criterion(0.65, -150.0)
        assert kelly > 0

    def test_underdog_price_positive(self):
        """Bet on underdog at +200."""
        # p=0.40, price=+200: b=2.0, kelly=(0.40*2.0-0.60)/2.0 = 0.10
        kelly = _kelly_criterion(0.40, 200.0)
        assert abs(kelly - 0.10) < 0.01


# ---------------------------------------------------------------------------
# Decision classification tests
# ---------------------------------------------------------------------------


class TestClassifyDecision:
    """Test play classification logic."""

    def test_no_market_returns_no_play(self):
        result = _classify_decision(
            p_conservative=0.55,
            p_market=None,
            market_price=None,
            target_bet_line=110.0,
            confidence_tier="high",
        )
        assert result == "no_play"

    def test_very_low_confidence_always_no_play(self):
        result = _classify_decision(
            p_conservative=0.55,
            p_market=0.45,
            market_price=120.0,
            target_bet_line=110.0,
            confidence_tier="very_low",
        )
        assert result == "no_play"

    def test_no_edge_returns_no_play(self):
        """When p_conservative < p_market → no edge → no play."""
        result = _classify_decision(
            p_conservative=0.48,
            p_market=0.52,
            market_price=-110.0,
            target_bet_line=110.0,
            confidence_tier="high",
        )
        assert result == "no_play"

    def test_edge_exists_but_below_target_returns_lean(self):
        """Small edge but market price doesn't beat target → lean."""
        result = _classify_decision(
            p_conservative=0.54,
            p_market=0.52,
            market_price=-110.0,  # Not better than target
            target_bet_line=-105.0,  # Target is less negative
            confidence_tier="medium",
        )
        assert result == "lean"

    def test_beats_target_returns_playable(self):
        """Edge exists and market price beats target → playable."""
        result = _classify_decision(
            p_conservative=0.55,
            p_market=0.48,
            market_price=110.0,  # Better than target
            target_bet_line=105.0,
            confidence_tier="medium",
        )
        assert result == "playable"

    def test_strong_play_requires_high_confidence_and_big_edge(self):
        result = _classify_decision(
            p_conservative=0.60,
            p_market=0.48,
            market_price=110.0,
            target_bet_line=100.0,
            confidence_tier="high",
        )
        assert result == "strong_play"


# ---------------------------------------------------------------------------
# Price comparison helper
# ---------------------------------------------------------------------------


class TestPriceBeatsThreshold:

    def test_less_negative_beats_more_negative(self):
        """For favorites: -110 is better than -150."""
        assert _price_beats_threshold(-110.0, -150.0, is_favorite=True)

    def test_more_positive_beats_less_positive(self):
        """For underdogs: +130 is better than +110."""
        assert _price_beats_threshold(130.0, 110.0, is_favorite=False)

    def test_same_price_does_not_beat(self):
        assert not _price_beats_threshold(-110.0, -110.0, is_favorite=True)


# ---------------------------------------------------------------------------
# Full compute_fair_odds integration
# ---------------------------------------------------------------------------


class TestComputeFairOdds:
    """Integration tests for the full decision engine."""

    def _make_uncertainty(self, tier: str = "medium") -> UncertaintyResult:
        from app.analytics.calibration.uncertainty import TIER_PENALTIES
        return UncertaintyResult(
            penalty=TIER_PENALTIES[tier],
            confidence_tier=tier,
            factors={"sim_variance": 0.1, "profile_freshness": 0.1,
                     "market_disagreement": 0.1, "pitcher_data": 0.0},
        )

    def test_returns_fair_odds_decision(self):
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=None,
            uncertainty=self._make_uncertainty(),
        )
        assert isinstance(result, FairOddsDecision)

    def test_favorite_fair_line_is_negative(self):
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=None,
            uncertainty=self._make_uncertainty(),
        )
        assert result.fair_line_mid < 0
        assert result.p_true == 0.55

    def test_underdog_fair_line_is_positive(self):
        result = compute_fair_odds(
            calibrated_wp=0.45,
            market_price=None,
            uncertainty=self._make_uncertainty(),
        )
        assert result.fair_line_mid > 0

    def test_conservative_less_extreme_than_true(self):
        """Conservative line should be closer to even money."""
        result = compute_fair_odds(
            calibrated_wp=0.60,
            market_price=None,
            uncertainty=self._make_uncertainty(),
        )
        # Fair line mid is more negative than conservative
        assert result.fair_line_conservative > result.fair_line_mid  # Less negative

    def test_kelly_positive_with_edge(self):
        """When market price is better than conservative fair, Kelly > 0."""
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=110.0,  # Getting plus money on a favorite
            uncertainty=self._make_uncertainty("high"),
        )
        assert result.kelly_fraction > 0
        assert result.half_kelly > 0
        assert result.quarter_kelly > 0

    def test_kelly_zero_without_market(self):
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=None,
            uncertainty=self._make_uncertainty(),
        )
        assert result.kelly_fraction == 0.0

    def test_edge_vs_market_computed(self):
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=-110.0,
            uncertainty=self._make_uncertainty(),
        )
        assert result.edge_vs_market is not None
        assert isinstance(result.edge_vs_market, float)

    def test_no_market_returns_no_play(self):
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=None,
            uncertainty=self._make_uncertainty(),
        )
        assert result.decision == "no_play"

    def test_strong_edge_with_high_confidence(self):
        """Big edge + high confidence + good price → playable or strong_play."""
        result = compute_fair_odds(
            calibrated_wp=0.60,
            market_price=120.0,  # Great plus money on a favorite
            uncertainty=self._make_uncertainty("high"),
        )
        assert result.decision in ("playable", "strong_play")

    def test_fifty_fifty_game(self):
        """50/50 game should have near-zero edge and no play."""
        result = compute_fair_odds(
            calibrated_wp=0.50,
            market_price=-110.0,
            uncertainty=self._make_uncertainty(),
        )
        # Conservative stays at 0.50
        assert result.p_conservative == 0.50
        # No edge at -110 for a 50/50 game
        assert result.decision == "no_play"

    def test_target_and_strong_lines_present(self):
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=100.0,
            uncertainty=self._make_uncertainty(),
        )
        assert result.target_bet_line != 0.0
        assert result.strong_bet_line != 0.0
        # Strong bet line should be more generous (higher American odds) than target
        assert result.strong_bet_line > result.target_bet_line

    def test_required_edge_includes_friction(self):
        from app.analytics.calibration.uncertainty import TAX_FRICTION_BUFFER, TIER_REQUIRED_EDGE
        result = compute_fair_odds(
            calibrated_wp=0.55,
            market_price=100.0,
            uncertainty=self._make_uncertainty("medium"),
        )
        expected = TIER_REQUIRED_EDGE["medium"] + TAX_FRICTION_BUFFER
        assert abs(result.required_edge - expected) < 0.001
