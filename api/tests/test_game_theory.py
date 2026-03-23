"""Tests for the game theory module.

Covers Kelly Criterion, Nash Equilibrium, Portfolio Optimization,
and Minimax / Regret Matching — both unit logic and API routes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.api.analytics_routes import router
from app.analytics.game_theory.kelly import (
    american_to_decimal,
    compute_kelly,
    compute_kelly_batch,
    kelly_fraction,
)
from app.analytics.game_theory.minimax import (
    GameNode,
    minimax,
    regret_matching,
    solve_minimax,
)
from app.analytics.game_theory.nash import (
    lineup_nash,
    pitch_selection_nash,
    solve_zero_sum,
)
from app.analytics.game_theory.portfolio import optimize_portfolio
from app.db import get_db


def _make_client():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_result.all.return_value = []
    mock_db.execute.return_value = mock_result
    mock_db.get.return_value = None

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app)


# ===========================================================================
# Kelly Criterion — unit tests
# ===========================================================================


class TestAmericanToDecimal:
    def test_negative_odds(self):
        assert american_to_decimal(-200) == pytest.approx(1.5)

    def test_positive_odds(self):
        assert american_to_decimal(200) == pytest.approx(3.0)

    def test_even_money(self):
        assert american_to_decimal(100) == pytest.approx(2.0)
        assert american_to_decimal(-100) == pytest.approx(2.0)

    def test_invalid_odds(self):
        with pytest.raises(ValueError):
            american_to_decimal(50)


class TestKellyFraction:
    def test_positive_edge(self):
        # 60% true prob, 2.0 decimal (even money) → f = (0.6*1 - 0.4)/1 = 0.2
        assert kelly_fraction(0.6, 2.0) == pytest.approx(0.2)

    def test_no_edge(self):
        # 50% true prob, 2.0 decimal → f = 0
        assert kelly_fraction(0.5, 2.0) == pytest.approx(0.0)

    def test_negative_edge(self):
        # 40% true prob, 2.0 decimal → negative kelly → clamped to 0
        assert kelly_fraction(0.4, 2.0) == 0.0

    def test_edge_cases(self):
        assert kelly_fraction(0.0, 2.0) == 0.0
        assert kelly_fraction(1.0, 2.0) == 0.0
        assert kelly_fraction(0.5, 1.0) == 0.0


class TestComputeKelly:
    def test_basic_positive_ev(self):
        result = compute_kelly(model_prob=0.6, american_odds=-110, bankroll=1000)
        assert result.edge > 0
        assert result.recommended_wager > 0
        assert result.kelly_variant == "half"
        assert result.bankroll == 1000

    def test_negative_ev_zero_wager(self):
        result = compute_kelly(model_prob=0.3, american_odds=-200, bankroll=1000)
        assert result.edge < 0
        assert result.recommended_wager == 0.0

    def test_full_kelly(self):
        result = compute_kelly(model_prob=0.6, american_odds=100, bankroll=1000, variant="full")
        assert result.kelly_variant == "full"
        assert result.recommended_wager >= result.half_kelly * 1000

    def test_quarter_kelly(self):
        result = compute_kelly(model_prob=0.6, american_odds=100, bankroll=1000, variant="quarter")
        assert result.kelly_variant == "quarter"

    def test_max_fraction_cap(self):
        # Very high edge should be capped
        result = compute_kelly(model_prob=0.9, american_odds=100, bankroll=1000, max_fraction=0.10)
        assert result.recommended_wager <= 100.0

    def test_invalid_variant(self):
        with pytest.raises(ValueError):
            compute_kelly(model_prob=0.6, american_odds=100, variant="triple")


class TestComputeKellyBatch:
    def test_multiple_bets(self):
        bets = [
            {"model_prob": 0.6, "american_odds": -110},
            {"model_prob": 0.55, "american_odds": 100},
        ]
        results = compute_kelly_batch(bets, bankroll=1000)
        assert len(results) == 2
        assert all(r.bankroll == 1000 for r in results)

    def test_exposure_scaling(self):
        bets = [
            {"model_prob": 0.7, "american_odds": 100},
            {"model_prob": 0.7, "american_odds": 100},
            {"model_prob": 0.7, "american_odds": 100},
        ]
        results = compute_kelly_batch(bets, bankroll=1000, max_total_exposure=0.30)
        total_wager = sum(r.recommended_wager for r in results)
        assert total_wager <= 300.01  # 30% of 1000 with rounding tolerance


# ===========================================================================
# Nash Equilibrium — unit tests
# ===========================================================================


class TestSolveZeroSum:
    def test_rock_paper_scissors(self):
        # Classic RPS: each strategy should be ~1/3
        matrix = [
            [0, -1, 1],   # Rock
            [1, 0, -1],   # Paper
            [-1, 1, 0],   # Scissors
        ]
        result = solve_zero_sum(matrix, max_iterations=50_000)
        for prob in result.row_strategy:
            assert 0.2 < prob < 0.45  # Should converge near 1/3
        assert abs(result.game_value) < 0.05  # Game value ~0

    def test_dominant_strategy(self):
        # Row 0 dominates (always better)
        matrix = [
            [5, 5],
            [1, 1],
        ]
        result = solve_zero_sum(matrix)
        assert result.row_strategy[0] > 0.9  # Should play row 0

    def test_empty_matrix(self):
        result = solve_zero_sum([])
        assert result.row_strategy == []
        assert result.game_value == 0.0

    def test_labels(self):
        matrix = [[1, 0], [0, 1]]
        result = solve_zero_sum(matrix, row_labels=["A", "B"], col_labels=["X", "Y"])
        assert result.row_labels == ["A", "B"]
        assert result.col_labels == ["X", "Y"]


class TestLineupNash:
    def test_basic_lineup(self):
        # 3 batters vs 2 pitchers
        matrix = [
            [0.350, 0.280],  # Batter 1
            [0.300, 0.320],  # Batter 2
            [0.270, 0.310],  # Batter 3
        ]
        result = lineup_nash(matrix, ["B1", "B2", "B3"], ["P1", "P2"])
        assert len(result.row_strategy) == 3
        assert len(result.col_strategy) == 2
        assert abs(sum(result.row_strategy) - 1.0) < 0.01


class TestPitchSelectionNash:
    def test_pitch_mix(self):
        outcomes = {
            "fastball": {"pull": 0.15, "opposite": 0.05},
            "slider": {"pull": 0.03, "opposite": 0.12},
            "changeup": {"pull": 0.08, "opposite": 0.08},
        }
        result = pitch_selection_nash(outcomes)
        assert len(result.row_strategy) == 3
        assert abs(sum(result.row_strategy) - 1.0) < 0.01


# ===========================================================================
# Portfolio Optimization — unit tests
# ===========================================================================


class TestOptimizePortfolio:
    def test_basic_portfolio(self):
        bets = [
            {"bet_id": "ml_1", "label": "NYY ML", "model_prob": 0.6, "american_odds": -110},
            {"bet_id": "ml_2", "label": "BOS ML", "model_prob": 0.55, "american_odds": 100},
        ]
        result = optimize_portfolio(bets, bankroll=1000)
        assert len(result.allocations) == 2
        assert result.total_weight <= 0.51  # max_total default 0.50
        assert result.bankroll == 1000

    def test_no_positive_ev_bets(self):
        bets = [
            {"bet_id": "b1", "label": "Bad bet", "model_prob": 0.3, "american_odds": -200},
        ]
        result = optimize_portfolio(bets)
        assert result.allocations[0].weight == 0.0

    def test_empty(self):
        result = optimize_portfolio([])
        assert result.allocations == []
        assert result.total_weight == 0.0

    def test_same_game_correlation(self):
        bets = [
            {"bet_id": "b1", "label": "ML", "model_prob": 0.6, "american_odds": -110, "game_id": "g1"},
            {"bet_id": "b2", "label": "Over", "model_prob": 0.55, "american_odds": -110, "game_id": "g1"},
            {"bet_id": "b3", "label": "Other ML", "model_prob": 0.6, "american_odds": -110, "game_id": "g2"},
        ]
        result = optimize_portfolio(bets, bankroll=1000)
        assert result.total_weight > 0
        assert result.sharpe_ratio >= 0


# ===========================================================================
# Minimax — unit tests
# ===========================================================================


class TestMinimax:
    def test_simple_tree(self):
        # Max player chooses between two terminal values
        root = GameNode(is_maximizer=True, actions={"left": 3.0, "right": 7.0})
        action, value = minimax(root)
        assert action == "right"
        assert value == 7.0

    def test_two_level_tree(self):
        # Max → Min → terminals
        left_child = GameNode(is_maximizer=False, actions={"a": 3.0, "b": 5.0})
        right_child = GameNode(is_maximizer=False, actions={"c": 2.0, "d": 8.0})
        root = GameNode(is_maximizer=True, actions={"left": left_child, "right": right_child})
        action, value = minimax(root)
        # Min takes: left→3, right→2, so max picks left (3 > 2)
        assert action == "left"
        assert value == 3.0

    def test_solve_minimax(self):
        root = GameNode(is_maximizer=True, actions={"a": 10.0, "b": 5.0, "c": 8.0})
        result = solve_minimax(root)
        assert result.optimal_action == "a"
        assert result.action_values["a"] == 10.0


class TestRegretMatching:
    def test_symmetric_game(self):
        # Symmetric game should produce roughly uniform strategy
        matrix = [
            [0, -1, 1],
            [1, 0, -1],
            [-1, 1, 0],
        ]
        result = regret_matching(matrix, iterations=20_000)
        assert len(result.strategy) == 3
        for prob in result.strategy.values():
            assert 0.15 < prob < 0.50  # roughly uniform

    def test_dominant_action(self):
        matrix = [
            [10, 10],
            [1, 1],
        ]
        result = regret_matching(matrix)
        # Action 0 dominates
        assert result.strategy.get("action_0", 0) > 0.7

    def test_labels(self):
        matrix = [[1, 0], [0, 1]]
        result = regret_matching(matrix, row_labels=["X", "Y"], col_labels=["A", "B"])
        assert "X" in result.strategy
        assert "Y" in result.strategy


# ===========================================================================
# API Route tests
# ===========================================================================


class TestKellyRoute:
    def test_kelly_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/kelly", json={
            "model_prob": 0.6, "american_odds": -110, "bankroll": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["edge"] > 0
        assert data["recommended_wager"] > 0

    def test_kelly_batch_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/kelly/batch", json={
            "bets": [
                {"model_prob": 0.6, "american_odds": -110},
                {"model_prob": 0.55, "american_odds": 100},
            ],
            "bankroll": 1000,
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 2


class TestNashRoutes:
    def test_nash_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/nash", json={
            "payoff_matrix": [[1, -1], [-1, 1]],
            "max_iterations": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["row_strategy"]) == 2

    def test_lineup_nash_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/nash/lineup", json={
            "matchup_matrix": [[0.35, 0.28], [0.30, 0.32]],
            "batter_names": ["B1", "B2"],
            "pitcher_names": ["P1", "P2"],
        })
        assert resp.status_code == 200

    def test_pitch_selection_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/nash/pitch-selection", json={
            "pitch_outcomes": {
                "fastball": {"pull": 0.15, "opposite": 0.05},
                "slider": {"pull": 0.03, "opposite": 0.12},
            },
        })
        assert resp.status_code == 200


class TestPortfolioRoute:
    def test_portfolio_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/portfolio", json={
            "bets": [
                {"bet_id": "b1", "label": "ML", "model_prob": 0.6, "american_odds": -110},
            ],
            "bankroll": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["allocations"]) == 1


class TestMinimaxRoutes:
    def test_minimax_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/minimax", json={
            "tree": {
                "is_maximizer": True,
                "actions": {
                    "left": {"value": 3.0},
                    "right": {"value": 7.0},
                },
            },
        })
        assert resp.status_code == 200
        assert resp.json()["optimal_action"] == "right"

    def test_regret_matching_post(self):
        client = _make_client()
        resp = client.post("/api/analytics/game-theory/regret-matching", json={
            "payoff_matrix": [[1, -1], [-1, 1]],
            "iterations": 1000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "strategy" in data
