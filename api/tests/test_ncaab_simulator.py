"""Tests for NCAAB four-factor game simulator."""

import random

from app.analytics.sports.ncaab.constants import (
    DEFAULT_EVENT_PROBS,
    DEFAULT_EVENT_PROBS_SUFFIXED,
    HALVES,
    MAX_OVERTIMES,
    ORB_CHANCE,
    POSSESSION_EVENTS,
)
from app.analytics.sports.ncaab.game_simulator import NCAABGameSimulator
from app.analytics.sports.ncaab.metrics import NCAABMetrics


class TestNCAABConstants:
    def test_default_probs_sum_to_one(self):
        total = sum(DEFAULT_EVENT_PROBS.values())
        assert abs(total - 1.0) < 0.01

    def test_all_non_meta_events_have_probs(self):
        for event in POSSESSION_EVENTS:
            if event != "offensive_rebound":
                assert event in DEFAULT_EVENT_PROBS


class TestNCAABGameSimulator:
    def test_deterministic_with_seed(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r1 = sim.simulate_game(ctx, rng=random.Random(42))
        r2 = sim.simulate_game(ctx, rng=random.Random(42))
        assert r1["home_score"] == r2["home_score"]
        assert r1["away_score"] == r2["away_score"]

    def test_realistic_score_range(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        scores = []
        rng = random.Random(123)
        for _ in range(100):
            r = sim.simulate_game(ctx, rng=rng)
            scores.append(r["home_score"] + r["away_score"])
        avg = sum(scores) / len(scores)
        assert 110 < avg < 180, f"Average total score {avg} outside NCAAB range"

    def test_winner_always_determined(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        rng = random.Random(999)
        for _ in range(50):
            r = sim.simulate_game(ctx, rng=rng)
            assert r["winner"] in ("home", "away")
            assert r["home_score"] != r["away_score"]

    def test_regulation_game_has_two_periods(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        rng = random.Random(42)
        r = sim.simulate_game(ctx, rng=rng)
        assert r["periods_played"] >= HALVES

    def test_events_tracked(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r = sim.simulate_game(ctx, rng=random.Random(42))
        for event in POSSESSION_EVENTS:
            if event != "offensive_rebound":
                assert event in r["home_events"]
        assert r["home_events"]["possessions_total"] > 0

    def test_offensive_rebounds_tracked(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        # Run many games - ORBs should happen
        total_orbs = 0
        rng = random.Random(321)
        for _ in range(50):
            r = sim.simulate_game(ctx, rng=rng)
            total_orbs += r["home_events"].get("offensive_rebounds", 0)
            total_orbs += r["away_events"].get("offensive_rebounds", 0)
        assert total_orbs > 0, "No offensive rebounds in 50 games"

    def test_custom_probabilities(self):
        """Team with better four factors should win more."""
        sim = NCAABGameSimulator()
        good = {
            "two_pt_make_probability": 0.28,
            "three_pt_make_probability": 0.14,
            "free_throw_trip_probability": 0.08,
            "turnover_probability": 0.10,
        }
        bad = {
            "two_pt_make_probability": 0.16,
            "three_pt_make_probability": 0.07,
            "free_throw_trip_probability": 0.06,
            "turnover_probability": 0.22,
        }
        ctx = {"home_probabilities": good, "away_probabilities": bad}
        home_wins = 0
        rng = random.Random(777)
        for _ in range(200):
            r = sim.simulate_game(ctx, rng=rng)
            if r["winner"] == "home":
                home_wins += 1
        assert home_wins > 120, f"Good team should win majority: {home_wins}/200"

    def test_overtime_possible(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        ot_games = 0
        rng = random.Random(456)
        for _ in range(500):
            r = sim.simulate_game(ctx, rng=rng)
            if r["periods_played"] > HALVES:
                ot_games += 1
        assert ot_games > 0, "No OT games in 500 simulations"

    def test_result_keys(self):
        sim = NCAABGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r = sim.simulate_game(ctx, rng=random.Random(42))
        assert "home_score" in r
        assert "away_score" in r
        assert "winner" in r
        assert "home_events" in r
        assert "away_events" in r
        assert "periods_played" in r


class TestNCAABMetrics:
    def test_build_player_metrics(self):
        m = NCAABMetrics()
        stats = {"off_rating": 110.0, "ts_pct": 0.55, "usage_rate": 0.20, "game_score": 12.0}
        result = m.build_player_metrics(stats)
        assert isinstance(result, dict)

    def test_build_team_metrics(self):
        m = NCAABMetrics()
        stats = {
            "off_rating": 108.0, "def_rating": 100.0, "pace": 70.0,
            "off_efg_pct": 0.52, "off_tov_pct": 0.15, "off_orb_pct": 0.30, "off_ft_rate": 0.32,
            "def_efg_pct": 0.48, "def_tov_pct": 0.18, "def_orb_pct": 0.26, "def_ft_rate": 0.28,
        }
        result = m.build_team_metrics(stats)
        assert isinstance(result, dict)

    def test_build_player_profile(self):
        m = NCAABMetrics()
        stats = {"player_id": "789", "name": "Test Player"}
        profile = m.build_player_profile(stats)
        assert profile.sport == "ncaab"

    def test_build_team_profile(self):
        m = NCAABMetrics()
        stats = {"team_id": "DUKE", "name": "Duke"}
        profile = m.build_team_profile(stats)
        assert profile.sport == "ncaab"

    def test_build_matchup_metrics(self):
        m = NCAABMetrics()
        a = {"off_efg_pct": 0.54, "off_tov_pct": 0.14, "pace": 72.0}
        b = {"def_efg_pct": 0.46, "def_tov_pct": 0.20, "pace": 65.0}
        result = m.build_matchup_metrics(a, b)
        assert isinstance(result, dict)

    def test_empty_stats(self):
        m = NCAABMetrics()
        result = m.build_player_metrics({})
        assert isinstance(result, dict)
