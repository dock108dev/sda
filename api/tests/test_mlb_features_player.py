"""Tests for player-level PA features, handedness encoding, and normalization edge cases."""

from __future__ import annotations


from app.analytics.features.sports.mlb_features import (
    MLBFeatureBuilder,
    _encode_hand,
    _normalize,
    _normalize_default,
)


class TestEncodeHand:
    def test_right_hand(self):
        assert _encode_hand("R") == 1.0

    def test_left_hand(self):
        assert _encode_hand("L") == 0.0

    def test_switch(self):
        assert _encode_hand("S") == 0.5

    def test_unknown(self):
        assert _encode_hand("") == 0.5
        assert _encode_hand("X") == 0.5

    def test_case_insensitive(self):
        assert _encode_hand("r") == 1.0
        assert _encode_hand("l") == 0.0
        assert _encode_hand("s") == 0.5


class TestNormalize:
    def test_rate_stat_clamped(self):
        """Rate stats (baseline 0-1) are clamped to [0, 1]."""
        assert _normalize(1.5, 0.23) == 1.0
        assert _normalize(-0.1, 0.23) == 0.0
        assert _normalize(0.5, 0.23) == 0.5

    def test_absolute_stat_ratio(self):
        """Absolute stats divided by baseline."""
        assert abs(_normalize(180.0, 90.0) - 2.0) < 0.001

    def test_no_baseline(self):
        assert _normalize(42.0, None) == 42.0

    def test_zero_baseline(self):
        assert _normalize(5.0, 0) == 5.0


class TestNormalizeDefault:
    def test_none_baseline(self):
        assert _normalize_default(None) == 0.0

    def test_rate_baseline(self):
        assert _normalize_default(0.23) == 0.23
        assert _normalize_default(0.5) == 0.5

    def test_absolute_baseline(self):
        assert _normalize_default(90.0) == 1.0


class TestBuildPlayerPaFeatures:
    """Tests for the player_plate_appearance feature path."""

    def test_builds_features_with_all_data(self):
        builder = MLBFeatureBuilder()
        batter = {
            "contact_rate": 0.80,
            "whiff_rate": 0.20,
            "swing_rate": 0.48,
            "power_index": 0.15,
            "barrel_rate": 0.08,
            "hard_hit_rate": 0.38,
            "avg_exit_velo": 90.0,
            "z_swing_pct": 0.70,
            "o_swing_pct": 0.30,
            "z_contact_pct": 0.88,
            "o_contact_pct": 0.65,
            "chase_rate": 0.30,
            "discipline_index": 0.60,
            "plate_discipline_index": 0.55,
        }
        pitcher = {
            "k_rate": 0.28,
            "bb_rate": 0.07,
            "hr_rate": 0.02,
            "whiff_rate": 0.25,
            "z_contact_pct": 0.80,
            "chase_rate": 0.35,
            "avg_exit_velo_against": 87.0,
            "hard_hit_pct_against": 0.33,
            "barrel_pct_against": 0.06,
            "contact_suppression": 0.05,
            "power_suppression": 0.10,
            "strikeout_rate": 0.28,
            "walk_rate": 0.07,
        }
        matchup = {"batter_hand": "R", "pitcher_hand": "L"}
        fielding = {"team_oaa": 5.0, "team_drs": 3.0, "team_defensive_value": 0.8}

        fv = builder.build_player_pa_features(
            batter, pitcher, matchup=matchup, fielding=fielding,
        )
        features = fv.to_dict()
        assert len(features) > 0
        assert "matchup_batter_hand" in features
        assert features["matchup_batter_hand"] == 1.0  # R
        assert features["matchup_pitcher_hand"] == 0.0  # L
        # Fielding features should be included
        assert "fielding_team_oaa" in features
        assert "fielding_team_drs" in features

    def test_builds_without_fielding(self):
        builder = MLBFeatureBuilder()
        batter = {"contact_rate": 0.77}
        pitcher = {"k_rate": 0.22}

        fv = builder.build_player_pa_features(batter, pitcher)
        features = fv.to_dict()
        assert "matchup_batter_hand" in features
        # No fielding features
        assert "fielding_team_oaa" not in features

    def test_builds_with_empty_matchup(self):
        builder = MLBFeatureBuilder()
        fv = builder.build_player_pa_features({}, {}, matchup={})
        assert fv.to_dict()["matchup_batter_hand"] == 0.5  # unknown
        assert fv.to_dict()["matchup_pitcher_hand"] == 0.5

    def test_build_features_routes_player_pa(self):
        """build_features with model_type='player_plate_appearance' routes correctly."""
        builder = MLBFeatureBuilder()
        profiles = {
            "batter_profile": {"metrics": {"contact_rate": 0.80}},
            "pitcher_profile": {"metrics": {"k_rate": 0.25}},
            "matchup": {"batter_hand": "L"},
        }
        fv = builder.build_features(profiles, "player_plate_appearance")
        assert "matchup_batter_hand" in fv.to_dict()

    def test_build_features_unknown_model_type(self):
        """Unknown model_type returns empty features."""
        builder = MLBFeatureBuilder()
        fv = builder.build_features({}, "nonexistent_model")
        assert fv.to_dict() == {}

    def test_extract_metrics_non_dict_profile(self):
        """_extract_metrics returns {} for non-dict, non-object input."""
        from app.analytics.features.sports.mlb_features import _extract_metrics
        result = _extract_metrics({"batter_profile": 42}, "batter_profile", "batter")
        assert result == {}
