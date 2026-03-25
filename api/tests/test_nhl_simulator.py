"""Tests for NHL shot-based game simulator."""

import random

from app.analytics.sports.nhl.constants import (
    DEFAULT_EVENT_PROBS,
    DEFAULT_EVENT_PROBS_SUFFIXED,
    MAX_OVERTIMES,
    PERIODS,
    SHOT_EVENTS,
    SHOOTOUT_ROUNDS,
)
from app.analytics.sports.nhl.game_simulator import NHLGameSimulator
from app.analytics.sports.nhl.metrics import NHLMetrics


class TestNHLConstants:
    def test_default_probs_sum_to_one(self):
        total = sum(DEFAULT_EVENT_PROBS.values())
        assert abs(total - 1.0) < 0.01

    def test_all_events_have_probs(self):
        for event in SHOT_EVENTS:
            assert event in DEFAULT_EVENT_PROBS

    def test_suffixed_probs_match(self):
        for event in SHOT_EVENTS:
            key = f"{event}_probability"
            assert key in DEFAULT_EVENT_PROBS_SUFFIXED
            assert DEFAULT_EVENT_PROBS_SUFFIXED[key] == DEFAULT_EVENT_PROBS[event]


class TestNHLGameSimulator:
    def test_deterministic_with_seed(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r1 = sim.simulate_game(ctx, rng=random.Random(42))
        r2 = sim.simulate_game(ctx, rng=random.Random(42))
        assert r1["home_score"] == r2["home_score"]
        assert r1["away_score"] == r2["away_score"]

    def test_realistic_score_range(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        scores = []
        rng = random.Random(123)
        for _ in range(200):
            r = sim.simulate_game(ctx, rng=rng)
            scores.append(r["home_score"] + r["away_score"])
        avg = sum(scores) / len(scores)
        assert 3 < avg < 9, f"Average total goals {avg} outside NHL range"

    def test_winner_always_determined(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        rng = random.Random(999)
        for _ in range(100):
            r = sim.simulate_game(ctx, rng=rng)
            assert r["winner"] in ("home", "away")

    def test_regulation_game_periods(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        rng = random.Random(42)
        r = sim.simulate_game(ctx, rng=rng)
        assert r["periods_played"] >= PERIODS

    def test_events_tracked(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r = sim.simulate_game(ctx, rng=random.Random(42))
        for event in SHOT_EVENTS:
            assert event in r["home_events"]
        assert r["home_events"]["shots_total"] > 0

    def test_shootout_can_occur(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        shootout_games = 0
        rng = random.Random(789)
        for _ in range(500):
            r = sim.simulate_game(ctx, rng=rng)
            if r.get("went_to_shootout"):
                shootout_games += 1
        assert shootout_games > 0, "No shootout games in 500 simulations"

    def test_custom_probabilities(self):
        """Team with higher shooting pct should win more."""
        sim = NHLGameSimulator()
        good = {
            "goal_probability": 0.15,
            "blocked_shot_probability": 0.10,
            "missed_shot_probability": 0.10,
        }
        bad = {
            "goal_probability": 0.04,
            "blocked_shot_probability": 0.20,
            "missed_shot_probability": 0.16,
        }
        ctx = {"home_probabilities": good, "away_probabilities": bad}
        home_wins = 0
        rng = random.Random(555)
        for _ in range(200):
            r = sim.simulate_game(ctx, rng=rng)
            if r["winner"] == "home":
                home_wins += 1
        assert home_wins > 100, f"Good team should win majority: {home_wins}/200"

    def test_result_keys(self):
        sim = NHLGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r = sim.simulate_game(ctx, rng=random.Random(42))
        assert "home_score" in r
        assert "away_score" in r
        assert "winner" in r
        assert "home_events" in r
        assert "away_events" in r
        assert "periods_played" in r
        assert "went_to_shootout" in r


class TestNHLMetrics:
    def test_build_player_metrics(self):
        m = NHLMetrics()
        stats = {
            "goals": 2,
            "assists": 1,
            "shots": 5,
            "xgoals_for": 1.5,
            "game_score": 3.0,
        }
        result = m.build_player_metrics(stats)
        assert isinstance(result, dict)
        assert result["goals"] == 2.0
        assert result["points"] == 3.0
        assert result["shooting_pct"] == 0.4

    def test_build_team_metrics(self):
        m = NHLMetrics()
        stats = {
            "xgoals_for": 2.8,
            "xgoals_against": 2.5,
            "corsi_pct": 0.52,
            "shooting_pct": 0.10,
            "save_pct": 0.92,
        }
        result = m.build_team_metrics(stats)
        assert isinstance(result, dict)
        assert "xgoals_for" in result
        assert "xgoals_pct" in result

    def test_build_player_profile(self):
        m = NHLMetrics()
        stats = {"player_id": "456", "name": "Test Player"}
        profile = m.build_player_profile(stats)
        assert profile.sport == "nhl"
        assert profile.player_id == "456"
        assert profile.name == "Test Player"

    def test_build_team_profile(self):
        m = NHLMetrics()
        stats = {"team_id": "BOS", "name": "Bruins"}
        profile = m.build_team_profile(stats)
        assert profile.sport == "nhl"
        assert profile.team_id == "BOS"

    def test_build_matchup_metrics(self):
        m = NHLMetrics()
        a = {"xgoals_for": 3.0, "corsi_pct": 0.55}
        b = {"xgoals_for": 2.5, "corsi_pct": 0.48}
        result = m.build_matchup_metrics(a, b)
        assert isinstance(result, dict)
        assert result["xgoals_for_diff"] == 0.5
        assert "corsi_diff" in result

    def test_empty_stats(self):
        m = NHLMetrics()
        result = m.build_player_metrics({})
        assert isinstance(result, dict)
        assert len(result) == 0
