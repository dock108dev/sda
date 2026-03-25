"""Tests for multi-sport profile service extensions.

Verifies:
- Sport-specific stats_to_metrics helpers produce correct keys
- Sport-specific probability functions produce valid dicts
- The profile_to_probabilities dispatcher routes correctly
- _SPORT_CONFIG has entries for all supported sports
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.analytics.services.profile_service import (
    _SPORT_CONFIG,
    _nba_stats_to_metrics,
    _ncaab_stats_to_metrics,
    _nhl_stats_to_metrics,
    profile_to_nba_probabilities,
    profile_to_ncaab_probabilities,
    profile_to_nhl_probabilities,
    profile_to_pa_probabilities,
    profile_to_probabilities,
)


# ---------------------------------------------------------------------------
# Fixtures: fake ORM row objects
# ---------------------------------------------------------------------------

@pytest.fixture()
def nba_row():
    return SimpleNamespace(
        off_rating=112.5,
        def_rating=108.3,
        net_rating=4.2,
        pace=100.1,
        efg_pct=0.54,
        ts_pct=0.58,
        fg_pct=0.47,
        fg3_pct=0.37,
        ft_pct=0.80,
        orb_pct=0.25,
        drb_pct=0.75,
        reb_pct=0.50,
        ast_pct=0.60,
        tov_pct=0.12,
        ft_rate=0.28,
    )


@pytest.fixture()
def nhl_row():
    return SimpleNamespace(
        xgoals_for=2.8,
        xgoals_against=2.3,
        xgoals_pct=0.55,
        corsi_pct=0.53,
        fenwick_pct=0.52,
        shots_for=32,
        shots_against=28,
        shooting_pct=0.10,
        save_pct=0.92,
        pdo=1.02,
        high_danger_shots_for=10,
        high_danger_goals_for=4,
        high_danger_shots_against=8,
        high_danger_goals_against=2,
    )


@pytest.fixture()
def ncaab_row():
    return SimpleNamespace(
        off_rating=110.0,
        def_rating=95.0,
        net_rating=15.0,
        pace=68.5,
        off_efg_pct=0.53,
        off_tov_pct=0.17,
        off_orb_pct=0.32,
        off_ft_rate=0.35,
        def_efg_pct=0.45,
        def_tov_pct=0.22,
        def_orb_pct=0.25,
        def_ft_rate=0.28,
    )


# ---------------------------------------------------------------------------
# _SPORT_CONFIG tests
# ---------------------------------------------------------------------------

class TestSportConfig:
    def test_has_all_supported_sports(self):
        assert "mlb" in _SPORT_CONFIG
        assert "nba" in _SPORT_CONFIG
        assert "nhl" in _SPORT_CONFIG
        assert "ncaab" in _SPORT_CONFIG

    def test_config_tuple_structure(self):
        for sport, config in _SPORT_CONFIG.items():
            assert len(config) == 4, f"{sport} config should have 4 elements"
            league_code, module_path, class_name, metrics_fn = config
            assert isinstance(league_code, str)
            assert isinstance(module_path, str)
            assert isinstance(class_name, str)
            # metrics_fn is None for MLB, callable for others
            if sport == "mlb":
                assert metrics_fn is None
            else:
                assert callable(metrics_fn)

    def test_league_codes(self):
        assert _SPORT_CONFIG["mlb"][0] == "MLB"
        assert _SPORT_CONFIG["nba"][0] == "NBA"
        assert _SPORT_CONFIG["nhl"][0] == "NHL"
        assert _SPORT_CONFIG["ncaab"][0] == "NCAAB"


# ---------------------------------------------------------------------------
# stats_to_metrics tests
# ---------------------------------------------------------------------------

class TestNbaStatsToMetrics:
    def test_produces_correct_keys(self, nba_row):
        metrics = _nba_stats_to_metrics(nba_row)
        expected_keys = {
            "off_rating", "def_rating", "net_rating", "pace",
            "efg_pct", "ts_pct", "fg_pct", "fg3_pct", "ft_pct",
            "orb_pct", "drb_pct", "reb_pct", "ast_pct", "tov_pct", "ft_rate",
        }
        assert set(metrics.keys()) == expected_keys

    def test_values_are_floats(self, nba_row):
        metrics = _nba_stats_to_metrics(nba_row)
        for k, v in metrics.items():
            assert isinstance(v, float), f"{k} should be float"

    def test_none_values_excluded(self):
        row = SimpleNamespace(
            off_rating=110.0,
            def_rating=None,
            net_rating=5.0,
            pace=None,
            efg_pct=0.50,
            ts_pct=None,
            fg_pct=0.45,
            fg3_pct=None,
            ft_pct=0.78,
            orb_pct=None,
            drb_pct=0.70,
            reb_pct=None,
            ast_pct=0.55,
            tov_pct=None,
            ft_rate=0.25,
        )
        metrics = _nba_stats_to_metrics(row)
        assert "def_rating" not in metrics
        assert "pace" not in metrics
        assert "off_rating" in metrics


class TestNhlStatsToMetrics:
    def test_produces_correct_keys(self, nhl_row):
        metrics = _nhl_stats_to_metrics(nhl_row)
        expected_keys = {
            "xgoals_for", "xgoals_against", "xgoals_pct",
            "corsi_pct", "fenwick_pct",
            "shots_for", "shots_against", "shooting_pct", "save_pct", "pdo",
            "high_danger_shots_for", "high_danger_goals_for",
            "high_danger_shots_against", "high_danger_goals_against",
        }
        assert set(metrics.keys()) == expected_keys

    def test_values_are_floats(self, nhl_row):
        metrics = _nhl_stats_to_metrics(nhl_row)
        for k, v in metrics.items():
            assert isinstance(v, float), f"{k} should be float"

    def test_none_values_excluded(self):
        row = SimpleNamespace(
            xgoals_for=2.5,
            xgoals_against=None,
            xgoals_pct=0.52,
            corsi_pct=None,
            fenwick_pct=0.51,
            shots_for=30,
            shots_against=None,
            shooting_pct=0.09,
            save_pct=None,
            pdo=1.00,
        )
        metrics = _nhl_stats_to_metrics(row)
        assert "xgoals_against" not in metrics
        assert "xgoals_for" in metrics

    def test_high_danger_included_when_present(self, nhl_row):
        metrics = _nhl_stats_to_metrics(nhl_row)
        assert "high_danger_shots_for" in metrics
        assert "high_danger_goals_for" in metrics

    def test_high_danger_excluded_when_missing(self):
        row = SimpleNamespace(
            xgoals_for=2.5, xgoals_against=2.0, xgoals_pct=0.52,
            corsi_pct=0.50, fenwick_pct=0.51,
            shots_for=30, shots_against=28,
            shooting_pct=0.09, save_pct=0.91, pdo=1.00,
        )
        metrics = _nhl_stats_to_metrics(row)
        assert "high_danger_shots_for" not in metrics


class TestNcaabStatsToMetrics:
    def test_produces_correct_keys(self, ncaab_row):
        metrics = _ncaab_stats_to_metrics(ncaab_row)
        expected_keys = {
            "off_rating", "def_rating", "net_rating", "pace",
            "off_efg_pct", "off_tov_pct", "off_orb_pct", "off_ft_rate",
            "def_efg_pct", "def_tov_pct", "def_orb_pct", "def_ft_rate",
        }
        assert set(metrics.keys()) == expected_keys

    def test_values_are_floats(self, ncaab_row):
        metrics = _ncaab_stats_to_metrics(ncaab_row)
        for k, v in metrics.items():
            assert isinstance(v, float), f"{k} should be float"

    def test_none_values_excluded(self):
        row = SimpleNamespace(
            off_rating=105.0, def_rating=None, net_rating=None, pace=70.0,
            off_efg_pct=0.50, off_tov_pct=None, off_orb_pct=0.30, off_ft_rate=None,
            def_efg_pct=0.48, def_tov_pct=None, def_orb_pct=0.28, def_ft_rate=None,
        )
        metrics = _ncaab_stats_to_metrics(row)
        assert "def_rating" not in metrics
        assert "off_rating" in metrics


# ---------------------------------------------------------------------------
# Probability function tests
# ---------------------------------------------------------------------------

def _assert_valid_probs(probs: dict[str, float], *, check_sum: bool = True):
    """Helper: all values in [0, 1] and optionally sum close to 1."""
    assert len(probs) > 0, "probabilities dict should not be empty"
    for k, v in probs.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0, 1]"
    if check_sum:
        total = sum(probs.values())
        # Allow some slack — not all dicts must sum to exactly 1.0
        assert 0.5 <= total <= 2.0, f"total={total} seems unreasonable"


class TestProfileToNbaProbabilities:
    def test_default_profile(self):
        probs = profile_to_nba_probabilities({})
        _assert_valid_probs(probs)
        expected_keys = {
            "turnover_probability", "ft_trip_probability",
            "two_pt_make_probability", "three_pt_make_probability",
            "miss_probability", "offensive_rebound_probability",
        }
        assert set(probs.keys()) == expected_keys

    def test_high_efg_produces_more_makes(self):
        low = profile_to_nba_probabilities({"efg_pct": 0.40})
        high = profile_to_nba_probabilities({"efg_pct": 0.60})
        low_makes = low["two_pt_make_probability"] + low["three_pt_make_probability"]
        high_makes = high["two_pt_make_probability"] + high["three_pt_make_probability"]
        assert high_makes > low_makes

    def test_high_tov_produces_more_turnovers(self):
        low = profile_to_nba_probabilities({"tov_pct": 0.08})
        high = profile_to_nba_probabilities({"tov_pct": 0.20})
        assert high["turnover_probability"] > low["turnover_probability"]

    def test_sim_event_probs_reasonable(self):
        probs = profile_to_nba_probabilities({
            "efg_pct": 0.52, "tov_pct": 0.13, "fg3_pct": 0.36,
            "ft_rate": 0.25, "orb_pct": 0.25,
        })
        # Core events (excluding orb) should sum near 1.0
        core = (
            probs["turnover_probability"] + probs["ft_trip_probability"]
            + probs["two_pt_make_probability"] + probs["three_pt_make_probability"]
            + probs["miss_probability"]
        )
        assert 0.90 <= core <= 1.05


class TestProfileToNhlProbabilities:
    def test_default_profile(self):
        probs = profile_to_nhl_probabilities({})
        _assert_valid_probs(probs)
        expected_keys = {
            "goal_probability", "save_probability",
            "blocked_probability", "missed_probability",
            "possession_share",
        }
        assert set(probs.keys()) == expected_keys

    def test_higher_shooting_pct_more_goals(self):
        low = profile_to_nhl_probabilities({"shooting_pct": 0.05})
        high = profile_to_nhl_probabilities({"shooting_pct": 0.15})
        assert high["goal_probability"] > low["goal_probability"]

    def test_shot_outcomes_sum_to_one(self):
        probs = profile_to_nhl_probabilities({
            "shooting_pct": 0.09, "save_pct": 0.91,
            "xgoals_pct": 0.50, "corsi_pct": 0.50,
        })
        shot_total = (
            probs["goal_probability"] + probs["save_probability"]
            + probs["blocked_probability"] + probs["missed_probability"]
        )
        assert abs(shot_total - 1.0) < 0.01


class TestProfileToNcaabProbabilities:
    def test_default_profile(self):
        probs = profile_to_ncaab_probabilities({})
        _assert_valid_probs(probs)
        expected_keys = {
            "turnover_probability", "ft_trip_probability",
            "two_pt_make_probability", "three_pt_make_probability",
            "miss_probability", "offensive_rebound_probability",
        }
        assert set(probs.keys()) == expected_keys

    def test_high_tov_produces_more_turnovers(self):
        low = profile_to_ncaab_probabilities({"off_tov_pct": 0.10})
        high = profile_to_ncaab_probabilities({"off_tov_pct": 0.25})
        assert high["turnover_probability"] > low["turnover_probability"]

    def test_sim_event_probs_reasonable(self):
        probs = profile_to_ncaab_probabilities({
            "off_efg_pct": 0.50, "off_tov_pct": 0.18,
            "off_orb_pct": 0.30, "off_ft_rate": 0.30,
        })
        core = (
            probs["turnover_probability"] + probs["ft_trip_probability"]
            + probs["two_pt_make_probability"] + probs["three_pt_make_probability"]
            + probs["miss_probability"]
        )
        assert 0.90 <= core <= 1.05


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------

class TestProfileToProbabilitiesDispatcher:
    def test_routes_mlb(self):
        result = profile_to_probabilities("mlb", {})
        assert "strikeout_probability" in result

    def test_routes_nba(self):
        result = profile_to_probabilities("nba", {})
        assert "turnover_probability" in result
        assert "two_pt_make_probability" in result

    def test_routes_nhl(self):
        result = profile_to_probabilities("nhl", {})
        assert "goal_probability" in result

    def test_routes_ncaab(self):
        result = profile_to_probabilities("ncaab", {})
        assert "turnover_probability" in result

    def test_case_insensitive(self):
        assert profile_to_probabilities("MLB", {}) == profile_to_probabilities("mlb", {})
        assert profile_to_probabilities("NBA", {}) == profile_to_probabilities("nba", {})
        assert profile_to_probabilities("NHL", {}) == profile_to_probabilities("nhl", {})
        assert profile_to_probabilities("NCAAB", {}) == profile_to_probabilities("ncaab", {})

    def test_unknown_sport_returns_empty(self):
        assert profile_to_probabilities("cricket", {}) == {}
        assert profile_to_probabilities("", {}) == {}

    def test_mlb_matches_direct_call(self):
        profile = {"whiff_rate": 0.25, "barrel_rate": 0.08}
        assert profile_to_probabilities("mlb", profile) == profile_to_pa_probabilities(profile)

    def test_nba_matches_direct_call(self):
        profile = {"efg_pct": 0.54, "tov_pct": 0.12}
        assert profile_to_probabilities("nba", profile) == profile_to_nba_probabilities(profile)

    def test_nhl_matches_direct_call(self):
        profile = {"shooting_pct": 0.10, "save_pct": 0.92}
        assert profile_to_probabilities("nhl", profile) == profile_to_nhl_probabilities(profile)

    def test_ncaab_matches_direct_call(self):
        profile = {"off_efg_pct": 0.52, "off_tov_pct": 0.17}
        assert profile_to_probabilities("ncaab", profile) == profile_to_ncaab_probabilities(profile)
