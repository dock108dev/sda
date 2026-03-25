"""Tests for NBA possession-based game simulator."""
import random
from app.analytics.sports.nba.game_simulator import NBAGameSimulator
from app.analytics.sports.nba.constants import (
    POSSESSION_EVENTS,
    DEFAULT_EVENT_PROBS,
    DEFAULT_EVENT_PROBS_SUFFIXED,
    POINTS_PER_EVENT,
    QUARTERS,
    MAX_OVERTIMES,
)
from app.analytics.sports.nba.metrics import NBAMetrics


class TestNBAConstants:
    """Test NBA constants are well-formed."""

    def test_default_probs_sum_to_one(self):
        total = sum(DEFAULT_EVENT_PROBS.values())
        assert abs(total - 1.0) < 0.01

    def test_all_events_have_probs(self):
        for event in POSSESSION_EVENTS:
            assert event in DEFAULT_EVENT_PROBS

    def test_all_events_have_points(self):
        for event in POSSESSION_EVENTS:
            assert event in POINTS_PER_EVENT


class TestNBAGameSimulator:
    """Test NBA game simulator."""

    def test_deterministic_with_seed(self):
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r1 = sim.simulate_game(ctx, rng=random.Random(42))
        r2 = sim.simulate_game(ctx, rng=random.Random(42))
        assert r1["home_score"] == r2["home_score"]
        assert r1["away_score"] == r2["away_score"]

    def test_realistic_score_range(self):
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        scores = []
        rng = random.Random(123)
        for _ in range(100):
            r = sim.simulate_game(ctx, rng=rng)
            scores.append(r["home_score"] + r["away_score"])
        avg = sum(scores) / len(scores)
        assert 180 < avg < 260, f"Average total score {avg} outside NBA range"

    def test_winner_always_determined(self):
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        rng = random.Random(999)
        for _ in range(50):
            r = sim.simulate_game(ctx, rng=rng)
            assert r["winner"] in ("home", "away")
            assert r["home_score"] != r["away_score"]

    def test_regulation_game_has_four_periods(self):
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        rng = random.Random(42)
        r = sim.simulate_game(ctx, rng=rng)
        assert r["periods_played"] >= QUARTERS

    def test_events_tracked(self):
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r = sim.simulate_game(ctx, rng=random.Random(42))
        for event in POSSESSION_EVENTS:
            assert event in r["home_events"]
            assert event in r["away_events"]
        assert r["home_events"]["possessions_total"] > 0
        assert r["away_events"]["possessions_total"] > 0

    def test_custom_probabilities(self):
        """Team with higher shooting should score more on average."""
        sim = NBAGameSimulator()
        good_shooting = {
            "two_pt_make_probability": 0.32,
            "three_pt_make_probability": 0.18,
            "free_throw_trip_probability": 0.10,
            "turnover_probability": 0.08,
        }
        bad_shooting = {
            "two_pt_make_probability": 0.18,
            "three_pt_make_probability": 0.08,
            "free_throw_trip_probability": 0.10,
            "turnover_probability": 0.18,
        }
        ctx = {"home_probabilities": good_shooting, "away_probabilities": bad_shooting}
        home_wins = 0
        rng = random.Random(777)
        for _ in range(200):
            r = sim.simulate_game(ctx, rng=rng)
            if r["winner"] == "home":
                home_wins += 1
        assert home_wins > 120, f"Good team should win majority: {home_wins}/200"

    def test_overtime_possible(self):
        """Run many games to verify OT can occur."""
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        ot_games = 0
        rng = random.Random(456)
        for _ in range(500):
            r = sim.simulate_game(ctx, rng=rng)
            if r["periods_played"] > QUARTERS:
                ot_games += 1
        # OT should happen occasionally
        assert ot_games > 0, "No OT games in 500 simulations"

    def test_result_keys(self):
        sim = NBAGameSimulator()
        ctx = {"home_probabilities": {}, "away_probabilities": {}}
        r = sim.simulate_game(ctx, rng=random.Random(42))
        assert "home_score" in r
        assert "away_score" in r
        assert "winner" in r
        assert "home_events" in r
        assert "away_events" in r
        assert "periods_played" in r


class TestNBAMetrics:
    """Test NBA metrics computation."""

    def test_build_player_metrics(self):
        m = NBAMetrics()
        stats = {
            "off_rating": 115.0,
            "def_rating": 110.0,
            "ts_pct": 0.60,
            "efg_pct": 0.55,
            "ast_pct": 0.25,
            "tov_pct": 0.12,
            "orb_pct": 0.05,
            "usage_rate": 0.22,
        }
        result = m.build_player_metrics(stats)
        assert "off_rating" in result
        assert "ts_pct" in result

    def test_build_team_metrics(self):
        m = NBAMetrics()
        stats = {
            "off_rating": 115.0,
            "def_rating": 110.0,
            "net_rating": 5.0,
            "pace": 102.0,
            "efg_pct": 0.55,
            "ts_pct": 0.60,
            "tov_pct": 0.12,
            "orb_pct": 0.25,
            "ft_rate": 0.28,
        }
        result = m.build_team_metrics(stats)
        assert "team_off_rating" in result or "off_rating" in result

    def test_build_player_profile(self):
        m = NBAMetrics()
        stats = {"player_id": "123", "name": "Test Player", "off_rating": 115.0}
        profile = m.build_player_profile(stats)
        assert profile.sport == "nba"
        assert profile.player_id == "123"

    def test_build_team_profile(self):
        m = NBAMetrics()
        stats = {"team_id": "BOS", "name": "Celtics", "off_rating": 118.0}
        profile = m.build_team_profile(stats)
        assert profile.sport == "nba"

    def test_build_matchup_metrics(self):
        m = NBAMetrics()
        team_a = {"off_rating": 118.0, "pace": 102.0, "efg_pct": 0.56}
        team_b = {"off_rating": 108.0, "pace": 96.0, "def_rating": 112.0}
        result = m.build_matchup_metrics(team_a, team_b)
        assert isinstance(result, dict)

    def test_empty_stats(self):
        m = NBAMetrics()
        result = m.build_player_metrics({})
        assert isinstance(result, dict)
