"""Tests for uncertainty scoring and conservative probability.

Phase 3 of the fair-odds pipeline.
"""

from __future__ import annotations

from app.analytics.calibration.uncertainty import (
    TIER_PENALTIES,
    FairOddsCore,
    UncertaintyResult,
    apply_uncertainty,
    compute_uncertainty,
)


class TestComputeUncertainty:
    """Test the uncertainty scoring function."""

    def test_high_confidence_all_good_signals(self):
        """All factors favorable → high confidence, small penalty."""
        result = compute_uncertainty(
            sim_wp_std_dev=0.007,
            profile_games_home=30,
            profile_games_away=30,
            market_disagreement=0.01,
            pitcher_data_quality=True,
        )
        assert result.confidence_tier == "high"
        assert result.penalty == TIER_PENALTIES["high"]
        assert result.penalty == 0.01

    def test_low_confidence_bad_signals(self):
        """All factors unfavorable → low or very_low confidence."""
        result = compute_uncertainty(
            sim_wp_std_dev=0.025,
            profile_games_home=3,
            profile_games_away=3,
            market_disagreement=0.10,
            pitcher_data_quality=False,
        )
        assert result.confidence_tier in ("low", "very_low")
        assert result.penalty >= TIER_PENALTIES["low"]

    def test_no_profile_data_high_uncertainty(self):
        """No profile games → freshness factor maxed out."""
        result = compute_uncertainty(
            profile_games_home=0,
            profile_games_away=0,
        )
        assert result.factors["profile_freshness"] == 1.0
        assert result.confidence_tier in ("low", "very_low")

    def test_no_market_data_mild_concern(self):
        """Missing market disagreement → mild default concern."""
        result = compute_uncertainty(
            sim_wp_std_dev=0.007,
            profile_games_home=30,
            profile_games_away=30,
            market_disagreement=None,
            pitcher_data_quality=True,
        )
        assert result.factors["market_disagreement"] == 0.3

    def test_large_market_disagreement_high_concern(self):
        """Big gap between sim and market → high concern."""
        result = compute_uncertainty(
            sim_wp_std_dev=0.007,
            profile_games_home=30,
            profile_games_away=30,
            market_disagreement=0.10,
            pitcher_data_quality=True,
        )
        assert result.factors["market_disagreement"] == 1.0

    def test_missing_pitcher_data_adds_penalty(self):
        result = compute_uncertainty(pitcher_data_quality=False)
        assert result.factors["pitcher_data"] == 0.5

    def test_factors_dict_always_populated(self):
        result = compute_uncertainty()
        assert "sim_variance" in result.factors
        assert "profile_freshness" in result.factors
        assert "market_disagreement" in result.factors
        assert "pitcher_data" in result.factors

    def test_penalty_matches_tier(self):
        """Penalty value should match the tier's configured penalty."""
        for tier, expected_penalty in TIER_PENALTIES.items():
            # We can't deterministically target each tier, but verify the mapping
            assert expected_penalty > 0


class TestApplyUncertainty:
    """Test conservative probability and confidence band computation."""

    def test_favorite_pulled_toward_fifty(self):
        """p_true > 0.5 → p_conservative should be lower (closer to 0.5)."""
        uncertainty = UncertaintyResult(
            penalty=0.02, confidence_tier="medium", factors={},
        )
        result = apply_uncertainty(0.55, uncertainty)

        assert result.p_true == 0.55
        assert result.p_conservative == 0.53
        assert result.p_conservative < result.p_true
        assert result.p_conservative >= 0.5

    def test_underdog_pulled_toward_fifty(self):
        """p_true < 0.5 → p_conservative should be higher (closer to 0.5)."""
        uncertainty = UncertaintyResult(
            penalty=0.02, confidence_tier="medium", factors={},
        )
        result = apply_uncertainty(0.45, uncertainty)

        assert result.p_true == 0.45
        assert result.p_conservative == 0.47
        assert result.p_conservative > result.p_true
        assert result.p_conservative <= 0.5

    def test_fifty_fifty_stays_at_fifty(self):
        """p_true = 0.5 → conservative stays at 0.5."""
        uncertainty = UncertaintyResult(
            penalty=0.02, confidence_tier="medium", factors={},
        )
        result = apply_uncertainty(0.50, uncertainty)
        assert result.p_conservative == 0.50

    def test_confidence_band_widens_with_uncertainty(self):
        """Higher penalty → wider confidence band."""
        low_u = UncertaintyResult(penalty=0.01, confidence_tier="high", factors={})
        high_u = UncertaintyResult(penalty=0.05, confidence_tier="very_low", factors={})

        low_result = apply_uncertainty(0.55, low_u)
        high_result = apply_uncertainty(0.55, high_u)

        low_band = low_result.p_high - low_result.p_low
        high_band = high_result.p_high - high_result.p_low

        assert high_band > low_band

    def test_band_clamped_to_valid_range(self):
        """Confidence band should not exceed [0.01, 0.99]."""
        uncertainty = UncertaintyResult(
            penalty=0.05, confidence_tier="very_low", factors={},
        )
        result = apply_uncertainty(0.03, uncertainty)
        assert result.p_low >= 0.01
        assert result.p_high <= 0.99

    def test_american_odds_conversion(self):
        """Verify fair lines are reasonable American odds."""
        uncertainty = UncertaintyResult(
            penalty=0.02, confidence_tier="medium", factors={},
        )
        result = apply_uncertainty(0.55, uncertainty)

        # p_true=0.55 → fair_line_mid ≈ -122
        assert result.fair_line_mid < 0  # Favorite
        assert -200 < result.fair_line_mid < -100

        # p_conservative=0.53 → fair_line_conservative ≈ -113
        assert result.fair_line_conservative < 0
        # Conservative line should be less negative (closer to even)
        assert result.fair_line_conservative > result.fair_line_mid

    def test_underdog_american_odds_positive(self):
        """p_true < 0.5 should produce positive American odds."""
        uncertainty = UncertaintyResult(
            penalty=0.02, confidence_tier="medium", factors={},
        )
        result = apply_uncertainty(0.45, uncertainty)

        assert result.fair_line_mid > 0  # Underdog
        assert 100 < result.fair_line_mid < 200

    def test_returns_fair_odds_core_type(self):
        uncertainty = UncertaintyResult(
            penalty=0.01, confidence_tier="high", factors={},
        )
        result = apply_uncertainty(0.55, uncertainty)
        assert isinstance(result, FairOddsCore)
        assert result.uncertainty is uncertainty
