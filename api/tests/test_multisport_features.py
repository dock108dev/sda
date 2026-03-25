"""Tests for NBA, NHL, and NCAAB feature builders and registry routing."""

from __future__ import annotations

import pytest

from app.analytics.features.core.feature_builder import FeatureBuilder
from app.analytics.features.core.feature_vector import FeatureVector
from app.analytics.features.sports.nba_features import NBAFeatureBuilder
from app.analytics.features.sports.nhl_features import NHLFeatureBuilder
from app.analytics.features.sports.ncaab_features import NCAABFeatureBuilder
from app.analytics.sports.nba.constants import FEATURE_BASELINES as NBA_BASELINES
from app.analytics.sports.nhl.constants import FEATURE_BASELINES as NHL_BASELINES
from app.analytics.sports.ncaab.constants import FEATURE_BASELINES as NCAAB_BASELINES


# ---------------------------------------------------------------------------
# NBA Feature Builder
# ---------------------------------------------------------------------------


class TestNBAFeatureBuilder:
    """Tests for NBAFeatureBuilder."""

    def _make_profiles(self, home_metrics=None, away_metrics=None):
        return {
            "home_profile": {"metrics": home_metrics or {}},
            "away_profile": {"metrics": away_metrics or {}},
        }

    def test_builds_correct_feature_keys_possession(self):
        profiles = self._make_profiles(
            home_metrics={"off_rating": 115.0, "def_rating": 110.0},
            away_metrics={"off_rating": 112.0},
        )
        builder = NBAFeatureBuilder()
        vec = builder.build_features(profiles, "possession")
        names = vec.feature_names
        assert "home_off_rating" in names
        assert "home_def_rating" in names
        assert "away_off_rating" in names
        assert "away_pace" in names  # should be present even if 0.0
        assert len(names) == 20  # 10 home + 10 away

    def test_game_model_type_works(self):
        profiles = self._make_profiles(
            home_metrics={"off_rating": 115.0},
        )
        builder = NBAFeatureBuilder()
        vec = builder.build_features(profiles, "game")
        assert vec.size == 20

    def test_normalizes_against_baselines(self):
        builder = NBAFeatureBuilder()
        profiles = self._make_profiles(
            home_metrics={"off_rating": 228.0},  # 2x baseline (114.0)
        )
        vec = builder.build_features(profiles, "possession")
        assert vec.get("home_off_rating") == pytest.approx(2.0, abs=0.01)

    def test_missing_profiles_return_zero(self):
        builder = NBAFeatureBuilder()
        vec = builder.build_features({}, "possession")
        assert all(v == 0.0 for v in vec.to_array())
        assert vec.size == 20

    def test_returns_feature_vector_instance(self):
        builder = NBAFeatureBuilder()
        vec = builder.build_features({}, "possession")
        assert isinstance(vec, FeatureVector)

    def test_unknown_model_type_returns_empty(self):
        builder = NBAFeatureBuilder()
        vec = builder.build_features({}, "unknown")
        assert vec.size == 0

    def test_object_with_metrics_attribute(self):
        """Profile objects with a .metrics attribute should work."""

        class FakeProfile:
            def __init__(self, metrics):
                self.metrics = metrics

        profiles = {
            "home_profile": FakeProfile({"off_rating": 114.0}),
            "away_profile": FakeProfile({}),
        }
        builder = NBAFeatureBuilder()
        vec = builder.build_features(profiles, "possession")
        assert vec.get("home_off_rating") == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# NHL Feature Builder
# ---------------------------------------------------------------------------


class TestNHLFeatureBuilder:
    """Tests for NHLFeatureBuilder."""

    def _make_profiles(self, home_metrics=None, away_metrics=None):
        return {
            "home_profile": {"metrics": home_metrics or {}},
            "away_profile": {"metrics": away_metrics or {}},
        }

    def test_builds_correct_feature_keys_shot(self):
        profiles = self._make_profiles(
            home_metrics={"xgoals_for": 3.0, "corsi_pct": 0.52},
        )
        builder = NHLFeatureBuilder()
        vec = builder.build_features(profiles, "shot")
        names = vec.feature_names
        assert "home_xgoals_for" in names
        assert "home_corsi_pct" in names
        assert "away_save_pct" in names
        assert len(names) == 14  # 7 home + 7 away

    def test_game_model_type_works(self):
        builder = NHLFeatureBuilder()
        vec = builder.build_features(self._make_profiles(), "game")
        assert vec.size == 14

    def test_normalizes_against_baselines(self):
        builder = NHLFeatureBuilder()
        profiles = self._make_profiles(
            home_metrics={"xgoals_for": 5.6},  # 2x baseline (2.80)
        )
        vec = builder.build_features(profiles, "shot")
        assert vec.get("home_xgoals_for") == pytest.approx(2.0, abs=0.01)

    def test_missing_profiles_return_zero(self):
        builder = NHLFeatureBuilder()
        vec = builder.build_features({}, "shot")
        assert all(v == 0.0 for v in vec.to_array())
        assert vec.size == 14

    def test_returns_feature_vector_instance(self):
        builder = NHLFeatureBuilder()
        vec = builder.build_features({}, "shot")
        assert isinstance(vec, FeatureVector)

    def test_unknown_model_type_returns_empty(self):
        builder = NHLFeatureBuilder()
        vec = builder.build_features({}, "unknown")
        assert vec.size == 0


# ---------------------------------------------------------------------------
# NCAAB Feature Builder
# ---------------------------------------------------------------------------


class TestNCAABFeatureBuilder:
    """Tests for NCAABFeatureBuilder."""

    def _make_profiles(self, home_metrics=None, away_metrics=None):
        return {
            "home_profile": {"metrics": home_metrics or {}},
            "away_profile": {"metrics": away_metrics or {}},
        }

    def test_builds_correct_feature_keys_possession(self):
        profiles = self._make_profiles(
            home_metrics={"off_rating": 108.0, "off_efg_pct": 0.52},
        )
        builder = NCAABFeatureBuilder()
        vec = builder.build_features(profiles, "possession")
        names = vec.feature_names
        assert "home_off_rating" in names
        assert "home_off_efg_pct" in names
        assert "home_def_tov_pct" in names
        assert "away_off_ft_rate" in names
        assert len(names) == 22  # 11 home + 11 away

    def test_game_model_type_works(self):
        builder = NCAABFeatureBuilder()
        vec = builder.build_features(self._make_profiles(), "game")
        assert vec.size == 22

    def test_normalizes_against_baselines(self):
        builder = NCAABFeatureBuilder()
        profiles = self._make_profiles(
            home_metrics={"off_rating": 210.0},  # 2x baseline (105.0)
        )
        vec = builder.build_features(profiles, "possession")
        assert vec.get("home_off_rating") == pytest.approx(2.0, abs=0.01)

    def test_missing_profiles_return_zero(self):
        builder = NCAABFeatureBuilder()
        vec = builder.build_features({}, "possession")
        assert all(v == 0.0 for v in vec.to_array())
        assert vec.size == 22

    def test_returns_feature_vector_instance(self):
        builder = NCAABFeatureBuilder()
        vec = builder.build_features({}, "possession")
        assert isinstance(vec, FeatureVector)

    def test_unknown_model_type_returns_empty(self):
        builder = NCAABFeatureBuilder()
        vec = builder.build_features({}, "unknown")
        assert vec.size == 0


# ---------------------------------------------------------------------------
# FeatureBuilder Registry Routing
# ---------------------------------------------------------------------------


class TestFeatureBuilderRegistry:
    """Tests that FeatureBuilder correctly routes to sport-specific builders."""

    def test_routes_to_nba(self):
        fb = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {"off_rating": 115.0}},
            "away_profile": {"metrics": {}},
        }
        vec = fb.build_features("nba", profiles, "possession")
        assert isinstance(vec, FeatureVector)
        assert "home_off_rating" in vec.feature_names

    def test_routes_to_nhl(self):
        fb = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {"xgoals_for": 3.0}},
            "away_profile": {"metrics": {}},
        }
        vec = fb.build_features("nhl", profiles, "shot")
        assert isinstance(vec, FeatureVector)
        assert "home_xgoals_for" in vec.feature_names

    def test_routes_to_ncaab(self):
        fb = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {"off_rating": 108.0}},
            "away_profile": {"metrics": {}},
        }
        vec = fb.build_features("ncaab", profiles, "possession")
        assert isinstance(vec, FeatureVector)
        assert "home_off_rating" in vec.feature_names

    def test_routes_to_mlb(self):
        """Existing MLB routing still works."""
        fb = FeatureBuilder()
        profiles = {
            "batter_profile": {"metrics": {"contact_rate": 0.80}},
            "pitcher_profile": {"metrics": {}},
        }
        vec = fb.build_features("mlb", profiles, "plate_appearance")
        assert isinstance(vec, FeatureVector)
        assert "batter_contact_rate" in vec.feature_names

    def test_unknown_sport_returns_empty(self):
        fb = FeatureBuilder()
        vec = fb.build_features("cricket", {}, "game")
        assert isinstance(vec, FeatureVector)
        assert vec.size == 0

    def test_case_insensitive_sport(self):
        fb = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {}},
            "away_profile": {"metrics": {}},
        }
        vec = fb.build_features("NBA", profiles, "possession")
        assert vec.size == 20

    def test_config_applied_to_nba(self):
        fb = FeatureBuilder()
        profiles = {
            "home_profile": {"metrics": {"off_rating": 114.0}},
            "away_profile": {"metrics": {}},
        }
        config = {
            "home_off_rating": {"enabled": True, "weight": 2.0},
            "home_def_rating": {"enabled": False},
        }
        vec = fb.build_features("nba", profiles, "possession", config=config)
        assert "home_def_rating" not in vec.feature_names
        # home_off_rating = 114/114 = 1.0, then * 2.0 weight = 2.0
        assert vec.get("home_off_rating") == pytest.approx(2.0, abs=0.01)
