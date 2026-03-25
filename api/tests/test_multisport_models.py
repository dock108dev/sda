"""Tests for NBA, NHL, and NCAAB model stubs.

Validates that each model:
- Returns valid probability distributions from rule-based predict_proba
- Returns expected keys from predict()
- Reports correct sport and model_type via get_info()
- Is registered in the model registry and can be instantiated
"""

from __future__ import annotations

import pytest

from app.analytics.models.core.model_registry import ModelRegistry, _BUILTIN_MODELS
from app.analytics.models.sports.nba.possession_model import NBAPossessionModel
from app.analytics.models.sports.nba.game_model import NBAGameModel
from app.analytics.models.sports.nhl.shot_model import NHLShotModel
from app.analytics.models.sports.nhl.game_model import NHLGameModel
from app.analytics.models.sports.ncaab.possession_model import NCAABPossessionModel
from app.analytics.models.sports.ncaab.game_model import NCAABGameModel


# ---------------------------------------------------------------------------
# NBA Possession Model
# ---------------------------------------------------------------------------


class TestNBAPossessionModel:
    def test_predict_proba_returns_valid_distribution(self):
        model = NBAPossessionModel()
        probs = model.predict_proba({})
        assert all(v >= 0 for v in probs.values())
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_proba_with_features(self):
        model = NBAPossessionModel()
        probs = model.predict_proba({"efg_pct": 0.58, "tov_pct": 0.10})
        assert all(v >= 0 for v in probs.values())
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_returns_expected_keys(self):
        model = NBAPossessionModel()
        result = model.predict({})
        assert "event_probabilities" in result
        assert "predicted_event" in result

    def test_get_info(self):
        model = NBAPossessionModel()
        info = model.get_info()
        assert info["sport"] == "nba"
        assert info["model_type"] == "possession"


# ---------------------------------------------------------------------------
# NBA Game Model
# ---------------------------------------------------------------------------


class TestNBAGameModel:
    def test_predict_proba_returns_valid_distribution(self):
        model = NBAGameModel()
        probs = model.predict_proba({})
        assert 0 <= probs["home_win"] <= 1
        assert 0 <= probs["away_win"] <= 1
        assert abs(probs["home_win"] + probs["away_win"] - 1.0) < 0.01

    def test_predict_returns_expected_keys(self):
        model = NBAGameModel()
        result = model.predict({})
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert "expected_home_score" in result
        assert "expected_away_score" in result

    def test_predict_with_features(self):
        model = NBAGameModel()
        result = model.predict({
            "home_off_rating": 118.0,
            "home_def_rating": 110.0,
            "away_off_rating": 112.0,
            "away_def_rating": 115.0,
        })
        assert 0 < result["home_win_probability"] < 1

    def test_home_win_probability_bounded(self):
        model = NBAGameModel()
        result = model.predict({})
        wp = result["home_win_probability"]
        assert 0.20 <= wp <= 0.80

    def test_get_info(self):
        model = NBAGameModel()
        info = model.get_info()
        assert info["sport"] == "nba"
        assert info["model_type"] == "game"


# ---------------------------------------------------------------------------
# NHL Shot Model
# ---------------------------------------------------------------------------


class TestNHLShotModel:
    def test_predict_proba_returns_valid_distribution(self):
        model = NHLShotModel()
        probs = model.predict_proba({})
        assert all(v >= 0 for v in probs.values())
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_proba_with_features(self):
        model = NHLShotModel()
        probs = model.predict_proba({"shooting_pct": 0.12, "high_danger_rate": 0.30})
        assert all(v >= 0 for v in probs.values())
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_returns_expected_keys(self):
        model = NHLShotModel()
        result = model.predict({})
        assert "event_probabilities" in result
        assert "predicted_event" in result

    def test_get_info(self):
        model = NHLShotModel()
        info = model.get_info()
        assert info["sport"] == "nhl"
        assert info["model_type"] == "shot"


# ---------------------------------------------------------------------------
# NHL Game Model
# ---------------------------------------------------------------------------


class TestNHLGameModel:
    def test_predict_proba_returns_valid_distribution(self):
        model = NHLGameModel()
        probs = model.predict_proba({})
        assert 0 <= probs["home_win"] <= 1
        assert 0 <= probs["away_win"] <= 1
        assert abs(probs["home_win"] + probs["away_win"] - 1.0) < 0.01

    def test_predict_returns_expected_keys(self):
        model = NHLGameModel()
        result = model.predict({})
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert "expected_home_score" in result
        assert "expected_away_score" in result

    def test_predict_with_features(self):
        model = NHLGameModel()
        result = model.predict({
            "home_xgoals_for": 3.2,
            "home_xgoals_against": 2.5,
            "away_xgoals_for": 2.6,
            "away_xgoals_against": 3.0,
        })
        assert 0 < result["home_win_probability"] < 1

    def test_home_win_probability_bounded(self):
        model = NHLGameModel()
        result = model.predict({})
        wp = result["home_win_probability"]
        assert 0.20 <= wp <= 0.80

    def test_get_info(self):
        model = NHLGameModel()
        info = model.get_info()
        assert info["sport"] == "nhl"
        assert info["model_type"] == "game"


# ---------------------------------------------------------------------------
# NCAAB Possession Model
# ---------------------------------------------------------------------------


class TestNCAABPossessionModel:
    def test_predict_proba_returns_valid_distribution(self):
        model = NCAABPossessionModel()
        probs = model.predict_proba({})
        assert all(v >= 0 for v in probs.values())
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_proba_with_features(self):
        model = NCAABPossessionModel()
        probs = model.predict_proba({"off_efg_pct": 0.54, "off_tov_pct": 0.14})
        assert all(v >= 0 for v in probs.values())
        assert abs(sum(probs.values()) - 1.0) < 0.01

    def test_predict_returns_expected_keys(self):
        model = NCAABPossessionModel()
        result = model.predict({})
        assert "event_probabilities" in result
        assert "predicted_event" in result

    def test_get_info(self):
        model = NCAABPossessionModel()
        info = model.get_info()
        assert info["sport"] == "ncaab"
        assert info["model_type"] == "possession"


# ---------------------------------------------------------------------------
# NCAAB Game Model
# ---------------------------------------------------------------------------


class TestNCAABGameModel:
    def test_predict_proba_returns_valid_distribution(self):
        model = NCAABGameModel()
        probs = model.predict_proba({})
        assert 0 <= probs["home_win"] <= 1
        assert 0 <= probs["away_win"] <= 1
        assert abs(probs["home_win"] + probs["away_win"] - 1.0) < 0.01

    def test_predict_returns_expected_keys(self):
        model = NCAABGameModel()
        result = model.predict({})
        assert "home_win_probability" in result
        assert "away_win_probability" in result
        assert "expected_home_score" in result
        assert "expected_away_score" in result

    def test_predict_with_features(self):
        model = NCAABGameModel()
        result = model.predict({
            "home_off_rating": 115.0,
            "home_def_rating": 95.0,
            "away_off_rating": 100.0,
            "away_def_rating": 105.0,
        })
        assert 0 < result["home_win_probability"] < 1

    def test_home_win_probability_bounded(self):
        model = NCAABGameModel()
        result = model.predict({})
        wp = result["home_win_probability"]
        assert 0.20 <= wp <= 0.80

    def test_get_info(self):
        model = NCAABGameModel()
        info = model.get_info()
        assert info["sport"] == "ncaab"
        assert info["model_type"] == "game"


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------


class TestModelRegistry:
    def test_registry_has_nba_entries(self):
        assert ("nba", "possession") in _BUILTIN_MODELS
        assert ("nba", "game") in _BUILTIN_MODELS

    def test_registry_has_nhl_entries(self):
        assert ("nhl", "shot") in _BUILTIN_MODELS
        assert ("nhl", "game") in _BUILTIN_MODELS

    def test_registry_has_ncaab_entries(self):
        assert ("ncaab", "possession") in _BUILTIN_MODELS
        assert ("ncaab", "game") in _BUILTIN_MODELS

    def test_registry_instantiates_nba_possession(self):
        registry = ModelRegistry(registry_path=None)
        instance = registry.get_active_model_instance("nba", "possession")
        assert instance is not None
        assert instance.sport == "nba"
        assert instance.model_type == "possession"

    def test_registry_instantiates_nba_game(self):
        registry = ModelRegistry(registry_path=None)
        instance = registry.get_active_model_instance("nba", "game")
        assert instance is not None
        assert instance.sport == "nba"
        assert instance.model_type == "game"

    def test_registry_instantiates_nhl_shot(self):
        registry = ModelRegistry(registry_path=None)
        instance = registry.get_active_model_instance("nhl", "shot")
        assert instance is not None
        assert instance.sport == "nhl"
        assert instance.model_type == "shot"

    def test_registry_instantiates_nhl_game(self):
        registry = ModelRegistry(registry_path=None)
        instance = registry.get_active_model_instance("nhl", "game")
        assert instance is not None
        assert instance.sport == "nhl"
        assert instance.model_type == "game"

    def test_registry_instantiates_ncaab_possession(self):
        registry = ModelRegistry(registry_path=None)
        instance = registry.get_active_model_instance("ncaab", "possession")
        assert instance is not None
        assert instance.sport == "ncaab"
        assert instance.model_type == "possession"

    def test_registry_instantiates_ncaab_game(self):
        registry = ModelRegistry(registry_path=None)
        instance = registry.get_active_model_instance("ncaab", "game")
        assert instance is not None
        assert instance.sport == "ncaab"
        assert instance.model_type == "game"
