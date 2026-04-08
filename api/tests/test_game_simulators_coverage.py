"""Comprehensive tests for NBA, NCAAB, and NHL Monte Carlo game simulators.

Covers simulate_game, simulate_game_with_lineups, edge cases (zero probs,
missing profiles, overtime/shootout logic), score sanity, and win probability.
"""

from __future__ import annotations

import random

import pytest

from app.analytics.sports.nba.game_simulator import (
    NBAGameSimulator,
    _build_weights as nba_build_weights,
    _new_event_counts as nba_new_event_counts,
    _simulate_possession as nba_simulate_possession,
)
from app.analytics.sports.nba.constants import (
    POSSESSION_EVENTS as NBA_EVENTS,
    QUARTERS as NBA_QUARTERS,
)
from app.analytics.sports.ncaab.game_simulator import (
    NCAABGameSimulator,
    _build_weights as ncaab_build_weights,
    _new_event_counts as ncaab_new_event_counts,
    _resolve_possession as ncaab_resolve_possession,
)
from app.analytics.sports.nhl.game_simulator import (
    NHLGameSimulator,
    _build_weights as nhl_build_weights,
    _new_event_counts as nhl_new_event_counts,
    _simulate_shootout,
    _simulate_ot,
)
from app.analytics.sports.nhl.constants import (
    SHOT_EVENTS as NHL_EVENTS,
    PERIODS as NHL_PERIODS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_nba_weights(two_make=0.26, three_make=0.126, three_miss=0.224,
                      ft=0.10, turnover=0.13):
    """Build NBA-style weights list directly."""
    named = two_make + three_make + three_miss + ft + turnover
    two_miss = max(1.0 - named, 0.0)
    return [two_make, two_miss, three_make, three_miss, ft, turnover]


def _make_nhl_weights(goal=0.09, blocked=0.16, missed=0.13):
    """Build NHL-style weights list directly."""
    save_prob = max(1.0 - goal - blocked - missed, 0.0)
    return [goal, save_prob, blocked, missed]


# ---------------------------------------------------------------------------
# NBA Tests
# ---------------------------------------------------------------------------


class TestNBASimulateGame:
    """Tests for NBAGameSimulator.simulate_game."""

    def test_basic_result_keys(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert "home_score" in result
        assert "away_score" in result
        assert "winner" in result
        assert "home_events" in result
        assert "away_events" in result
        assert "periods_played" in result

    def test_scores_non_negative(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["home_score"] >= 0
        assert result["away_score"] >= 0

    def test_winner_is_home_or_away(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_periods_at_least_four(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["periods_played"] >= NBA_QUARTERS

    def test_deterministic_with_seed(self) -> None:
        sim = NBAGameSimulator()
        r1 = sim.simulate_game({}, rng=random.Random(123))
        r2 = sim.simulate_game({}, rng=random.Random(123))
        assert r1["home_score"] == r2["home_score"]
        assert r1["away_score"] == r2["away_score"]
        assert r1["winner"] == r2["winner"]

    def test_default_rng_created_when_none(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game({}, rng=None)
        assert result["winner"] in ("home", "away")

    def test_custom_probabilities(self) -> None:
        sim = NBAGameSimulator()
        # Team that makes every 3-pointer heavily
        ctx = {
            "home_probabilities": {"three_pt_make_probability": 0.6},
            "away_probabilities": {"three_pt_make_probability": 0.01},
        }
        results = [sim.simulate_game(ctx, rng=random.Random(i)) for i in range(50)]
        home_wins = sum(1 for r in results if r["winner"] == "home")
        # Home should win most games with such dominant 3PT shooting
        assert home_wins > 25

    def test_events_tracked(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["home_events"]["possessions_total"] > 0
        assert result["away_events"]["possessions_total"] > 0

    def test_empty_probabilities_uses_defaults(self) -> None:
        sim = NBAGameSimulator()
        result = sim.simulate_game(
            {"home_probabilities": {}, "away_probabilities": {}},
            rng=random.Random(42),
        )
        # Should still produce a valid game
        assert result["home_score"] >= 0
        assert result["away_score"] >= 0

    def test_reasonable_score_range(self) -> None:
        """NBA games typically score 70-150 per team."""
        sim = NBAGameSimulator()
        results = [sim.simulate_game({}, rng=random.Random(i)) for i in range(20)]
        for r in results:
            assert 30 < r["home_score"] < 200
            assert 30 < r["away_score"] < 200


class TestNBASimulateGameWithLineups:
    """Tests for NBAGameSimulator.simulate_game_with_lineups."""

    def _lineup_context(self):
        """Build a valid rotation-aware context."""
        w = _make_nba_weights()
        return {
            "home_starter_weights": w,
            "home_bench_weights": w,
            "away_starter_weights": w,
            "away_bench_weights": w,
            "home_starter_share": 0.70,
            "away_starter_share": 0.70,
        }

    def test_fallback_without_lineup_keys(self) -> None:
        """Should fall back to simulate_game when rotation keys absent."""
        sim = NBAGameSimulator()
        result = sim.simulate_game_with_lineups({}, rng=random.Random(42))
        assert result["winner"] in ("home", "away")
        assert result["periods_played"] >= NBA_QUARTERS

    def test_with_lineup_data(self) -> None:
        sim = NBAGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["winner"] in ("home", "away")
        assert result["home_score"] >= 0
        assert result["away_score"] >= 0

    def test_default_rng_lineup(self) -> None:
        sim = NBAGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=None)
        assert result["winner"] in ("home", "away")

    def test_starter_share_extremes(self) -> None:
        """100% starter share should still produce valid results."""
        sim = NBAGameSimulator()
        ctx = self._lineup_context()
        ctx["home_starter_share"] = 1.0
        ctx["away_starter_share"] = 1.0
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["home_score"] >= 0

    def test_ft_pct_overrides(self) -> None:
        sim = NBAGameSimulator()
        ctx = self._lineup_context()
        ctx["home_ft_pct_starter"] = 0.90
        ctx["home_ft_pct_bench"] = 0.50
        ctx["away_ft_pct_starter"] = 0.90
        ctx["away_ft_pct_bench"] = 0.50
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_periods_played_with_lineups(self) -> None:
        sim = NBAGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["periods_played"] >= NBA_QUARTERS


class TestNBAHelpers:
    """Tests for NBA helper functions."""

    def test_build_weights_defaults(self) -> None:
        weights = nba_build_weights({})
        assert len(weights) == len(NBA_EVENTS)
        assert all(w >= 0 for w in weights)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_build_weights_custom(self) -> None:
        probs = {
            "two_pt_make_probability": 0.30,
            "three_pt_make_probability": 0.15,
            "three_pt_miss_probability": 0.20,
            "free_throw_trip_probability": 0.10,
            "turnover_probability": 0.10,
        }
        weights = nba_build_weights(probs)
        assert weights[0] == 0.30  # two_pt_make
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_build_weights_negative_clipped(self) -> None:
        probs = {"two_pt_make_probability": -0.5}
        weights = nba_build_weights(probs)
        assert weights[0] == 0.0

    def test_build_weights_over_one_zero_miss(self) -> None:
        """When named probs exceed 1.0, two_pt_miss is clamped to 0."""
        probs = {
            "two_pt_make_probability": 0.5,
            "three_pt_make_probability": 0.3,
            "three_pt_miss_probability": 0.2,
            "free_throw_trip_probability": 0.1,
            "turnover_probability": 0.1,
        }
        weights = nba_build_weights(probs)
        assert weights[1] == 0.0  # two_pt_miss clamped

    def test_new_event_counts(self) -> None:
        counts = nba_new_event_counts()
        assert counts["possessions_total"] == 0
        for ev in NBA_EVENTS:
            assert counts[ev] == 0

    def test_simulate_possession_two_make(self) -> None:
        """Force a two_pt_make by setting its weight to 1.0."""
        weights = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        events = nba_new_event_counts()
        pts = nba_simulate_possession(weights, random.Random(1), events, 0.78)
        assert pts == 2
        assert events["two_pt_make"] == 1

    def test_simulate_possession_three_make(self) -> None:
        weights = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        events = nba_new_event_counts()
        pts = nba_simulate_possession(weights, random.Random(1), events, 0.78)
        assert pts == 3

    def test_simulate_possession_turnover(self) -> None:
        weights = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        events = nba_new_event_counts()
        pts = nba_simulate_possession(weights, random.Random(1), events, 0.78)
        assert pts == 0

    def test_simulate_possession_ft_trip(self) -> None:
        weights = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        events = nba_new_event_counts()
        # ft_pct=1.0 means both FTs made
        pts = nba_simulate_possession(weights, random.Random(1), events, 1.0)
        assert pts == 2

    def test_simulate_possession_ft_trip_zero_pct(self) -> None:
        weights = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        events = nba_new_event_counts()
        pts = nba_simulate_possession(weights, random.Random(1), events, 0.0)
        assert pts == 0


class TestNBAOvertime:
    """Test NBA overtime logic."""

    def test_overtime_can_occur(self) -> None:
        """Run many seeds and check at least one goes to OT."""
        sim = NBAGameSimulator()
        any_ot = False
        for seed in range(200):
            result = sim.simulate_game({}, rng=random.Random(seed))
            if result["periods_played"] > NBA_QUARTERS:
                any_ot = True
                break
        assert any_ot, "No overtime games found in 200 seeds"


class TestNBAWinProbability:
    """Test that win probability is between 0 and 1 over many sims."""

    def test_win_probability_range(self) -> None:
        sim = NBAGameSimulator()
        n = 100
        home_wins = sum(
            1 for i in range(n)
            if sim.simulate_game({}, rng=random.Random(i))["winner"] == "home"
        )
        win_pct = home_wins / n
        assert 0.0 <= win_pct <= 1.0


# ---------------------------------------------------------------------------
# NCAAB Tests
# ---------------------------------------------------------------------------


class TestNCAABSimulateGame:
    """Tests for NCAABGameSimulator.simulate_game."""

    def test_basic_result_keys(self) -> None:
        sim = NCAABGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert "home_score" in result
        assert "away_score" in result
        assert "winner" in result
        assert "home_events" in result
        assert "away_events" in result
        assert "periods_played" in result

    def test_scores_non_negative(self) -> None:
        sim = NCAABGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["home_score"] >= 0
        assert result["away_score"] >= 0

    def test_winner_valid(self) -> None:
        sim = NCAABGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_periods_at_least_two(self) -> None:
        sim = NCAABGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["periods_played"] >= 2  # 2 halves

    def test_deterministic(self) -> None:
        sim = NCAABGameSimulator()
        r1 = sim.simulate_game({}, rng=random.Random(99))
        r2 = sim.simulate_game({}, rng=random.Random(99))
        assert r1 == r2

    def test_default_rng(self) -> None:
        sim = NCAABGameSimulator()
        result = sim.simulate_game({}, rng=None)
        assert result["winner"] in ("home", "away")

    def test_custom_probabilities(self) -> None:
        sim = NCAABGameSimulator()
        ctx = {
            "home_probabilities": {"three_pt_make_probability": 0.6},
            "away_probabilities": {"three_pt_make_probability": 0.01},
        }
        results = [sim.simulate_game(ctx, rng=random.Random(i)) for i in range(50)]
        home_wins = sum(1 for r in results if r["winner"] == "home")
        assert home_wins > 25

    def test_orb_tracking(self) -> None:
        sim = NCAABGameSimulator()
        ctx = {"orb_home": 0.5, "orb_away": 0.5}
        result = sim.simulate_game(ctx, rng=random.Random(42))
        # With high ORB, at least some offensive rebounds should occur
        total_orbs = (
            result["home_events"].get("offensive_rebounds", 0)
            + result["away_events"].get("offensive_rebounds", 0)
        )
        assert total_orbs > 0

    def test_ft_pct_override(self) -> None:
        sim = NCAABGameSimulator()
        ctx = {"ft_pct_home": 1.0, "ft_pct_away": 0.0}
        result = sim.simulate_game(ctx, rng=random.Random(42))
        assert result["home_score"] >= 0

    def test_reasonable_score_range(self) -> None:
        """NCAAB games typically score 50-100 per team."""
        sim = NCAABGameSimulator()
        results = [sim.simulate_game({}, rng=random.Random(i)) for i in range(20)]
        for r in results:
            assert 15 < r["home_score"] < 150
            assert 15 < r["away_score"] < 150


class TestNCAABSimulateGameWithLineups:
    """Tests for NCAABGameSimulator.simulate_game_with_lineups."""

    def _lineup_context(self):
        named = 0.220 + 0.102 + 0.198 + 0.072 + 0.170
        two_miss = max(1.0 - named, 0.0)
        w = [0.220, two_miss, 0.102, 0.198, 0.072, 0.170]
        return {
            "home_starter_weights": w,
            "home_bench_weights": w,
            "away_starter_weights": w,
            "away_bench_weights": w,
            "home_starter_share": 0.70,
            "away_starter_share": 0.70,
        }

    def test_fallback_without_lineup_keys(self) -> None:
        sim = NCAABGameSimulator()
        result = sim.simulate_game_with_lineups({}, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_with_lineup_data(self) -> None:
        sim = NCAABGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["winner"] in ("home", "away")
        assert result["home_score"] >= 0

    def test_default_rng_lineup(self) -> None:
        sim = NCAABGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=None)
        assert result["winner"] in ("home", "away")

    def test_orb_pct_overrides(self) -> None:
        sim = NCAABGameSimulator()
        ctx = self._lineup_context()
        ctx["home_orb_pct_starter"] = 0.5
        ctx["home_orb_pct_bench"] = 0.1
        ctx["away_orb_pct_starter"] = 0.5
        ctx["away_orb_pct_bench"] = 0.1
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_ft_pct_overrides(self) -> None:
        sim = NCAABGameSimulator()
        ctx = self._lineup_context()
        ctx["home_ft_pct_starter"] = 0.90
        ctx["home_ft_pct_bench"] = 0.50
        ctx["away_ft_pct_starter"] = 0.90
        ctx["away_ft_pct_bench"] = 0.50
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_starter_share_all_starters(self) -> None:
        sim = NCAABGameSimulator()
        ctx = self._lineup_context()
        ctx["home_starter_share"] = 1.0
        ctx["away_starter_share"] = 1.0
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["periods_played"] >= 2


class TestNCAABHelpers:
    """Tests for NCAAB helper functions."""

    def test_build_weights_defaults(self) -> None:
        weights = ncaab_build_weights({})
        assert len(weights) == 6
        assert all(w >= 0 for w in weights)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_build_weights_negative_clipped(self) -> None:
        probs = {"two_pt_make_probability": -1.0}
        weights = ncaab_build_weights(probs)
        assert weights[0] == 0.0

    def test_new_event_counts(self) -> None:
        counts = ncaab_new_event_counts()
        assert counts["possessions_total"] == 0
        assert counts["offensive_rebounds"] == 0

    def test_resolve_possession_two_make(self) -> None:
        weights = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        events = ncaab_new_event_counts()
        pts = ncaab_resolve_possession(weights, random.Random(1), events, 0.28, 0.70, 0)
        assert pts == 2

    def test_resolve_possession_three_make(self) -> None:
        weights = [0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        events = ncaab_new_event_counts()
        pts = ncaab_resolve_possession(weights, random.Random(1), events, 0.28, 0.70, 0)
        assert pts == 3

    def test_resolve_possession_turnover(self) -> None:
        weights = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        events = ncaab_new_event_counts()
        pts = ncaab_resolve_possession(weights, random.Random(1), events, 0.28, 0.70, 0)
        assert pts == 0

    def test_resolve_possession_ft_trip_perfect(self) -> None:
        weights = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        events = ncaab_new_event_counts()
        pts = ncaab_resolve_possession(weights, random.Random(1), events, 0.28, 1.0, 0)
        assert pts == 2

    def test_resolve_possession_ft_trip_zero(self) -> None:
        weights = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        events = ncaab_new_event_counts()
        pts = ncaab_resolve_possession(weights, random.Random(1), events, 0.28, 0.0, 0)
        assert pts == 0

    def test_resolve_possession_miss_with_orb(self) -> None:
        """Miss with 100% ORB chance should produce an offensive rebound."""
        weights = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]  # always two_pt_miss
        events = ncaab_new_event_counts()
        # orb_pct=1.0, but consecutive_orbs=0, max is 3
        # The recursion will keep getting misses and ORBs up to the cap
        ncaab_resolve_possession(weights, random.Random(1), events, 1.0, 0.70, 0)
        assert events["offensive_rebounds"] > 0

    def test_resolve_possession_orb_cap(self) -> None:
        """At max consecutive ORBs, no more rebounds should occur."""
        weights = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
        events = ncaab_new_event_counts()
        ncaab_resolve_possession(weights, random.Random(1), events, 1.0, 0.70, 3)
        # At max consecutive, should not add any ORBs
        assert events["offensive_rebounds"] == 0


class TestNCAABOvertime:
    """Test NCAAB overtime logic."""

    def test_overtime_can_occur(self) -> None:
        sim = NCAABGameSimulator()
        any_ot = False
        for seed in range(300):
            result = sim.simulate_game({}, rng=random.Random(seed))
            if result["periods_played"] > 2:
                any_ot = True
                break
        assert any_ot, "No overtime games found in 300 seeds"


class TestNCAABWinProbability:
    def test_win_probability_range(self) -> None:
        sim = NCAABGameSimulator()
        n = 100
        home_wins = sum(
            1 for i in range(n)
            if sim.simulate_game({}, rng=random.Random(i))["winner"] == "home"
        )
        win_pct = home_wins / n
        assert 0.0 <= win_pct <= 1.0


# ---------------------------------------------------------------------------
# NHL Tests
# ---------------------------------------------------------------------------


class TestNHLSimulateGame:
    """Tests for NHLGameSimulator.simulate_game."""

    def test_basic_result_keys(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert "home_score" in result
        assert "away_score" in result
        assert "winner" in result
        assert "home_events" in result
        assert "away_events" in result
        assert "periods_played" in result
        assert "went_to_shootout" in result

    def test_scores_non_negative(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["home_score"] >= 0
        assert result["away_score"] >= 0

    def test_winner_valid(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_periods_at_least_three(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["periods_played"] >= NHL_PERIODS

    def test_deterministic(self) -> None:
        sim = NHLGameSimulator()
        r1 = sim.simulate_game({}, rng=random.Random(77))
        r2 = sim.simulate_game({}, rng=random.Random(77))
        assert r1 == r2

    def test_default_rng(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game({}, rng=None)
        assert result["winner"] in ("home", "away")

    def test_custom_goal_probability(self) -> None:
        sim = NHLGameSimulator()
        ctx = {
            "home_probabilities": {"goal_probability": 0.5},
            "away_probabilities": {"goal_probability": 0.01},
        }
        results = [sim.simulate_game(ctx, rng=random.Random(i)) for i in range(50)]
        home_wins = sum(1 for r in results if r["winner"] == "home")
        assert home_wins > 30

    def test_events_tracked(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game({}, rng=random.Random(42))
        assert result["home_events"]["shots_total"] > 0
        assert result["away_events"]["shots_total"] > 0

    def test_reasonable_score_range(self) -> None:
        """NHL games typically 0-8 goals per team."""
        sim = NHLGameSimulator()
        results = [sim.simulate_game({}, rng=random.Random(i)) for i in range(20)]
        for r in results:
            assert r["home_score"] < 20
            assert r["away_score"] < 20

    def test_scores_differ_after_resolution(self) -> None:
        """Winner should always have more points (no ties in final result)."""
        sim = NHLGameSimulator()
        for seed in range(50):
            result = sim.simulate_game({}, rng=random.Random(seed))
            assert result["home_score"] != result["away_score"]


class TestNHLSimulateGameWithLineups:
    """Tests for NHLGameSimulator.simulate_game_with_lineups."""

    def _lineup_context(self):
        w = _make_nhl_weights()
        return {
            "home_starter_weights": w,
            "home_bench_weights": w,
            "away_starter_weights": w,
            "away_bench_weights": w,
            "home_starter_share": 0.65,
            "away_starter_share": 0.65,
        }

    def test_fallback_without_lineup_keys(self) -> None:
        sim = NHLGameSimulator()
        result = sim.simulate_game_with_lineups({}, rng=random.Random(42))
        assert result["winner"] in ("home", "away")

    def test_with_lineup_data(self) -> None:
        sim = NHLGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["winner"] in ("home", "away")
        assert result["home_score"] >= 0

    def test_default_rng_lineup(self) -> None:
        sim = NHLGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=None)
        assert result["winner"] in ("home", "away")

    def test_went_to_shootout_key(self) -> None:
        sim = NHLGameSimulator()
        ctx = self._lineup_context()
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert isinstance(result["went_to_shootout"], bool)

    def test_starter_share_all_starters(self) -> None:
        sim = NHLGameSimulator()
        ctx = self._lineup_context()
        ctx["home_starter_share"] = 1.0
        ctx["away_starter_share"] = 1.0
        result = sim.simulate_game_with_lineups(ctx, rng=random.Random(42))
        assert result["periods_played"] >= NHL_PERIODS


class TestNHLHelpers:
    """Tests for NHL helper functions."""

    def test_build_weights_defaults(self) -> None:
        weights = nhl_build_weights({})
        assert len(weights) == len(NHL_EVENTS)
        assert all(w >= 0 for w in weights)
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_build_weights_custom(self) -> None:
        probs = {
            "goal_probability": 0.15,
            "blocked_shot_probability": 0.20,
            "missed_shot_probability": 0.10,
        }
        weights = nhl_build_weights(probs)
        assert weights[0] == 0.15  # goal
        assert abs(sum(weights) - 1.0) < 1e-9

    def test_build_weights_negative_clipped(self) -> None:
        probs = {"goal_probability": -0.5}
        weights = nhl_build_weights(probs)
        assert weights[0] == 0.0

    def test_new_event_counts(self) -> None:
        counts = nhl_new_event_counts()
        assert counts["shots_total"] == 0
        for ev in NHL_EVENTS:
            assert counts[ev] == 0


class TestNHLShootout:
    """Tests for NHL shootout simulation."""

    def test_shootout_returns_winner(self) -> None:
        winner = _simulate_shootout(random.Random(42), 0.33, 0.33)
        assert winner in ("home", "away")

    def test_shootout_deterministic(self) -> None:
        w1 = _simulate_shootout(random.Random(42), 0.33, 0.33)
        w2 = _simulate_shootout(random.Random(42), 0.33, 0.33)
        assert w1 == w2

    def test_shootout_high_home_prob(self) -> None:
        """Home with very high shootout prob should win most."""
        home_wins = sum(
            1 for i in range(100)
            if _simulate_shootout(random.Random(i), 0.99, 0.01) == "home"
        )
        assert home_wins > 80

    def test_shootout_zero_probs(self) -> None:
        """Both zero probs: sudden death fallback should eventually return."""
        winner = _simulate_shootout(random.Random(42), 0.0, 0.0)
        assert winner in ("home", "away")

    def test_shootout_perfect_probs(self) -> None:
        """Both perfect probs: tied rounds, sudden death."""
        winner = _simulate_shootout(random.Random(42), 1.0, 1.0)
        assert winner in ("home", "away")


class TestNHLOvertime:
    """Tests for NHL overtime logic."""

    def test_ot_returns_winner_or_none(self) -> None:
        weights = _make_nhl_weights()
        home_events = nhl_new_event_counts()
        away_events = nhl_new_event_counts()
        result = _simulate_ot(weights, weights, random.Random(42), home_events, away_events)
        assert result in ("home", "away", None)

    def test_ot_high_goal_rate(self) -> None:
        """With very high goal prob, OT should almost always produce a winner."""
        high_goal_weights = _make_nhl_weights(goal=0.9, blocked=0.05, missed=0.05)
        winners = []
        for seed in range(50):
            he = nhl_new_event_counts()
            ae = nhl_new_event_counts()
            w = _simulate_ot(high_goal_weights, high_goal_weights, random.Random(seed), he, ae)
            winners.append(w)
        decided = sum(1 for w in winners if w is not None)
        assert decided > 40

    def test_game_can_go_to_shootout(self) -> None:
        """With low scoring, some games should reach shootout."""
        sim = NHLGameSimulator()
        low_scoring_ctx = {
            "home_probabilities": {"goal_probability": 0.01},
            "away_probabilities": {"goal_probability": 0.01},
        }
        any_shootout = False
        for seed in range(200):
            result = sim.simulate_game(low_scoring_ctx, rng=random.Random(seed))
            if result["went_to_shootout"]:
                any_shootout = True
                break
        assert any_shootout, "No shootout games found in 200 seeds"

    def test_game_can_go_to_ot(self) -> None:
        """Some games should go to OT (periods_played > 3)."""
        sim = NHLGameSimulator()
        any_ot = False
        for seed in range(200):
            result = sim.simulate_game({}, rng=random.Random(seed))
            if result["periods_played"] > NHL_PERIODS:
                any_ot = True
                break
        assert any_ot, "No OT games found in 200 seeds"


class TestNHLWinProbability:
    def test_win_probability_range(self) -> None:
        sim = NHLGameSimulator()
        n = 100
        home_wins = sum(
            1 for i in range(n)
            if sim.simulate_game({}, rng=random.Random(i))["winner"] == "home"
        )
        win_pct = home_wins / n
        assert 0.0 <= win_pct <= 1.0


# ---------------------------------------------------------------------------
# NHL Lineup + Shootout integration
# ---------------------------------------------------------------------------


class TestNHLLineupShootout:
    """Test that lineup mode can also reach shootout."""

    def test_lineup_shootout(self) -> None:
        sim = NHLGameSimulator()
        low_goal = _make_nhl_weights(goal=0.01, blocked=0.20, missed=0.20)
        ctx = {
            "home_starter_weights": low_goal,
            "home_bench_weights": low_goal,
            "away_starter_weights": low_goal,
            "away_bench_weights": low_goal,
            "home_starter_share": 0.65,
            "away_starter_share": 0.65,
        }
        any_shootout = False
        for seed in range(200):
            result = sim.simulate_game_with_lineups(ctx, rng=random.Random(seed))
            if result["went_to_shootout"]:
                any_shootout = True
                break
        assert any_shootout, "No shootout games in lineup mode in 200 seeds"
