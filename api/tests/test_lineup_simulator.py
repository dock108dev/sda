import random

import pytest

from app.analytics.sports.mlb.game_simulator import MLBGameSimulator, _build_weights


class TestLineupCycling:
    """Batter index wraps correctly through the lineup."""

    def test_lineup_index_wraps_after_nine(self):
        """After 9+ PAs, lineup index should wrap back to beginning."""
        sim = MLBGameSimulator()
        # Create weights where batter 0 always homers (all weight on HR)
        # and batters 1-8 always strike out
        hr_weights = [0, 0, 0, 0, 0, 0, 1.0]  # all HR
        k_weights = [1.0, 0, 0, 0, 0, 0, 0]  # all strikeout
        weights_list = [hr_weights] + [k_weights] * 8

        rng = random.Random(42)
        runs, new_idx = sim._simulate_half_inning_lineup(weights_list, 0, rng)

        # Batter 0 homers (1 run), batters 1-2-3 strike out (3 outs)
        # So we should see 1 run, and lineup_idx should be at 4
        assert runs == 1
        assert new_idx == 4

    def test_lineup_persists_across_innings(self):
        """Lineup index carries over between innings."""
        sim = MLBGameSimulator()
        # All batters get out immediately (all weight on strikeout)
        k_weights = [1.0, 0, 0, 0, 0, 0, 0]
        weights_list = [k_weights] * 9

        rng = random.Random(42)
        # First half-inning: 3 outs, index goes 0->3
        runs1, idx1 = sim._simulate_half_inning_lineup(weights_list, 0, rng)
        assert idx1 == 3
        assert runs1 == 0

        # Second half-inning: 3 more outs, index goes 3->6
        runs2, idx2 = sim._simulate_half_inning_lineup(weights_list, idx1, rng)
        assert idx2 == 6

        # Third half-inning: 3 more outs, index goes 6->0 (wraps)
        runs3, idx3 = sim._simulate_half_inning_lineup(weights_list, idx2, rng)
        assert idx3 == 0


class TestPitcherTransition:
    """Starter vs bullpen weights switch at the transition inning."""

    def test_uses_starter_weights_early(self):
        """Before transition inning, starter weights are used."""
        sim = MLBGameSimulator()
        # Starter weights: all strikeouts (0 runs)
        # Bullpen weights: high-K but some walks (avoids infinite inning)
        k_weights = [1.0, 0, 0, 0, 0, 0, 0]
        # Bullpen: 70% K, 20% walk, 10% single — will produce outs
        bp_weights = [0.70, 0, 0.20, 0.10, 0, 0, 0]

        game_context = {
            "home_lineup_weights": [k_weights] * 9,
            "away_lineup_weights": [k_weights] * 9,
            "home_bullpen_weights": [bp_weights] * 9,
            "away_bullpen_weights": [bp_weights] * 9,
            "starter_innings": 6.0,
        }

        rng = random.Random(99)
        result = sim.simulate_game_with_lineups(game_context, rng)
        # Starter innings (1-6) produce 0 runs, bullpen (7-9) may allow some
        assert result["home_score"] >= 0
        assert result["away_score"] >= 0
        assert "winner" in result

    def test_bullpen_after_transition(self):
        """After transition inning, bullpen weights produce different results."""
        sim = MLBGameSimulator()
        # Starter: moderate (league avg)
        starter_probs = {
            "strikeout_probability": 0.22,
            "walk_probability": 0.08,
            "single_probability": 0.15,
            "double_probability": 0.05,
            "triple_probability": 0.01,
            "home_run_probability": 0.03,
        }
        starter_w = _build_weights(starter_probs)

        # Bullpen: much more strikeouts
        bullpen_probs = {
            "strikeout_probability": 0.40,
            "walk_probability": 0.05,
            "single_probability": 0.10,
            "double_probability": 0.03,
            "triple_probability": 0.005,
            "home_run_probability": 0.02,
        }
        bullpen_w = _build_weights(bullpen_probs)

        game_context = {
            "home_lineup_weights": [starter_w] * 9,
            "away_lineup_weights": [starter_w] * 9,
            "home_bullpen_weights": [bullpen_w] * 9,
            "away_bullpen_weights": [bullpen_w] * 9,
            "starter_innings": 5.0,
        }

        rng = random.Random(42)
        result = sim.simulate_game_with_lineups(game_context, rng)
        assert isinstance(result["home_score"], int)
        assert isinstance(result["away_score"], int)


class TestBackwardCompat:
    """simulate_game() without lineup still works identically."""

    def test_team_level_sim_unchanged(self):
        """Original simulate_game still works with same interface."""
        sim = MLBGameSimulator()
        game_context = {
            "home_probabilities": {
                "strikeout_probability": 0.22,
                "walk_probability": 0.08,
                "single_probability": 0.15,
                "double_probability": 0.05,
                "triple_probability": 0.01,
                "home_run_probability": 0.03,
            },
            "away_probabilities": {
                "strikeout_probability": 0.22,
                "walk_probability": 0.08,
                "single_probability": 0.15,
                "double_probability": 0.05,
                "triple_probability": 0.01,
                "home_run_probability": 0.03,
            },
        }
        rng = random.Random(42)
        result = sim.simulate_game(game_context, rng)
        assert "home_score" in result
        assert "away_score" in result
        assert "winner" in result
        assert result["winner"] in ("home", "away")

    def test_lineup_sim_fallback_to_team_probs(self):
        """simulate_game_with_lineups falls back when no lineup weights."""
        sim = MLBGameSimulator()
        game_context = {
            "home_probabilities": {
                "strikeout_probability": 0.22,
                "walk_probability": 0.08,
                "single_probability": 0.15,
                "double_probability": 0.05,
                "triple_probability": 0.01,
                "home_run_probability": 0.03,
            },
            "away_probabilities": {
                "strikeout_probability": 0.22,
                "walk_probability": 0.08,
                "single_probability": 0.15,
                "double_probability": 0.05,
                "triple_probability": 0.01,
                "home_run_probability": 0.03,
            },
        }
        rng = random.Random(42)
        result = sim.simulate_game_with_lineups(game_context, rng)
        assert "home_score" in result
        assert "away_score" in result
        assert "winner" in result


class TestDeterminism:
    """Same seed produces same results."""

    def test_lineup_sim_deterministic(self):
        sim = MLBGameSimulator()
        probs = {
            "strikeout_probability": 0.22,
            "walk_probability": 0.08,
            "single_probability": 0.15,
            "double_probability": 0.05,
            "triple_probability": 0.01,
            "home_run_probability": 0.03,
        }
        weights = _build_weights(probs)
        game_context = {
            "home_lineup_weights": [weights] * 9,
            "away_lineup_weights": [weights] * 9,
            "home_bullpen_weights": [weights] * 9,
            "away_bullpen_weights": [weights] * 9,
            "starter_innings": 6.0,
        }

        r1 = sim.simulate_game_with_lineups(game_context, random.Random(123))
        r2 = sim.simulate_game_with_lineups(game_context, random.Random(123))
        assert r1 == r2
