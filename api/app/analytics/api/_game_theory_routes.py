"""Game theory API endpoints.

All endpoints live under ``/api/analytics/game-theory/*``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.analytics.game_theory.kelly import compute_kelly, compute_kelly_batch
from app.analytics.game_theory.minimax import (
    GameNode,
    regret_matching,
    solve_minimax,
)
from app.analytics.game_theory.nash import (
    lineup_nash,
    pitch_selection_nash,
    solve_zero_sum,
)
from app.analytics.game_theory.portfolio import optimize_portfolio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/game-theory", tags=["game-theory"])


# ---------------------------------------------------------------------------
# Kelly Criterion
# ---------------------------------------------------------------------------


class KellyRequest(BaseModel):
    model_prob: float = Field(..., gt=0, lt=1, description="Model probability of winning")
    american_odds: float = Field(..., description="American odds from sportsbook")
    bankroll: float = Field(1000.0, gt=0, description="Total bankroll")
    variant: str = Field("half", description="'full', 'half', or 'quarter'")
    max_fraction: float = Field(0.25, gt=0, le=1, description="Per-bet cap")


class KellyBetInput(BaseModel):
    model_prob: float = Field(..., gt=0, lt=1)
    american_odds: float


class KellyBatchRequest(BaseModel):
    bets: list[KellyBetInput]
    bankroll: float = Field(1000.0, gt=0)
    variant: str = Field("half")
    max_fraction: float = Field(0.25, gt=0, le=1)
    max_total_exposure: float = Field(0.50, gt=0, le=1)


@router.post("/kelly")
async def post_kelly(req: KellyRequest) -> dict[str, Any]:
    """Compute optimal bet size using the Kelly Criterion."""
    result = compute_kelly(
        model_prob=req.model_prob,
        american_odds=req.american_odds,
        bankroll=req.bankroll,
        variant=req.variant,
        max_fraction=req.max_fraction,
    )
    return asdict(result)


@router.post("/kelly/batch")
async def post_kelly_batch(req: KellyBatchRequest) -> dict[str, Any]:
    """Compute Kelly sizing for multiple bets with exposure management."""
    results = compute_kelly_batch(
        bets=[b.model_dump() for b in req.bets],
        bankroll=req.bankroll,
        variant=req.variant,
        max_fraction=req.max_fraction,
        max_total_exposure=req.max_total_exposure,
    )
    return {"results": [asdict(r) for r in results], "count": len(results)}


# ---------------------------------------------------------------------------
# Nash Equilibrium
# ---------------------------------------------------------------------------


class NashRequest(BaseModel):
    payoff_matrix: list[list[float]] = Field(..., description="M×N payoff matrix for row player")
    row_labels: list[str] | None = Field(None, description="Row action labels")
    col_labels: list[str] | None = Field(None, description="Column action labels")
    max_iterations: int = Field(10_000, ge=100, le=100_000)


class LineupNashRequest(BaseModel):
    matchup_matrix: list[list[float]] = Field(
        ..., description="Rows=batters, Cols=pitchers, values=expected outcome (e.g., wOBA)",
    )
    batter_names: list[str]
    pitcher_names: list[str]


class PitchSelectionRequest(BaseModel):
    pitch_outcomes: dict[str, dict[str, float]] = Field(
        ..., description="pitch_type -> batter_stance -> expected run value",
    )


@router.post("/nash")
async def post_nash(req: NashRequest) -> dict[str, Any]:
    """Solve a two-player zero-sum game for Nash Equilibrium."""
    result = solve_zero_sum(
        payoff_matrix=req.payoff_matrix,
        row_labels=req.row_labels,
        col_labels=req.col_labels,
        max_iterations=req.max_iterations,
    )
    return asdict(result)


@router.post("/nash/lineup")
async def post_lineup_nash(req: LineupNashRequest) -> dict[str, Any]:
    """Find optimal lineup decisions given batter-vs-pitcher matchup values."""
    result = lineup_nash(
        matchup_matrix=req.matchup_matrix,
        batter_names=req.batter_names,
        pitcher_names=req.pitcher_names,
    )
    return asdict(result)


@router.post("/nash/pitch-selection")
async def post_pitch_selection(req: PitchSelectionRequest) -> dict[str, Any]:
    """Find optimal pitch selection mix against batter stances."""
    result = pitch_selection_nash(pitch_outcomes=req.pitch_outcomes)
    return asdict(result)


# ---------------------------------------------------------------------------
# Portfolio Optimization
# ---------------------------------------------------------------------------


class PortfolioBetInput(BaseModel):
    bet_id: str = Field("", description="Unique identifier")
    label: str = Field("", description="Display name")
    model_prob: float = Field(..., gt=0, lt=1)
    american_odds: float
    game_id: str | None = Field(None, description="Game ID for correlation grouping")


class PortfolioRequest(BaseModel):
    bets: list[PortfolioBetInput]
    bankroll: float = Field(1000.0, gt=0)
    correlation_matrix: list[list[float]] | None = Field(None)
    risk_aversion: float = Field(2.0, ge=0.1, le=10.0)
    max_per_bet: float = Field(0.20, gt=0, le=1)
    max_total: float = Field(0.50, gt=0, le=1)


@router.post("/portfolio")
async def post_portfolio(req: PortfolioRequest) -> dict[str, Any]:
    """Optimize bankroll allocation across multiple bets."""
    result = optimize_portfolio(
        bets=[b.model_dump() for b in req.bets],
        bankroll=req.bankroll,
        correlation_matrix=req.correlation_matrix,
        risk_aversion=req.risk_aversion,
        max_per_bet=req.max_per_bet,
        max_total=req.max_total,
    )
    return {
        "allocations": [asdict(a) for a in result.allocations],
        "total_weight": result.total_weight,
        "expected_portfolio_return": result.expected_portfolio_return,
        "portfolio_variance": result.portfolio_variance,
        "portfolio_std": result.portfolio_std,
        "sharpe_ratio": result.sharpe_ratio,
        "bankroll": result.bankroll,
    }


# ---------------------------------------------------------------------------
# Minimax / Regret Matching
# ---------------------------------------------------------------------------


class RegretMatchingRequest(BaseModel):
    payoff_matrix: list[list[float]] = Field(..., description="M×N payoff matrix")
    row_labels: list[str] | None = None
    col_labels: list[str] | None = None
    iterations: int = Field(10_000, ge=100, le=100_000)


class MinimaxTreeAction(BaseModel):
    """Recursive tree node for minimax."""
    value: float | None = Field(None, description="Terminal value (if leaf)")
    is_maximizer: bool | None = Field(None, description="Player type (if subtree)")
    actions: dict[str, MinimaxTreeAction] | None = Field(None, description="Child actions")


class MinimaxRequest(BaseModel):
    tree: MinimaxTreeAction = Field(..., description="Game tree root")
    depth: int = Field(20, ge=1, le=50)


def _build_game_node(req: MinimaxTreeAction) -> GameNode | float:
    """Recursively build a GameNode from the request model."""
    if req.value is not None:
        return req.value
    actions: dict[str, GameNode | float] = {}
    if req.actions:
        for name, child in req.actions.items():
            actions[name] = _build_game_node(child)
    return GameNode(is_maximizer=req.is_maximizer or False, actions=actions)


@router.post("/minimax")
async def post_minimax(req: MinimaxRequest) -> dict[str, Any]:
    """Solve a sequential game tree using minimax with alpha-beta pruning."""
    root = _build_game_node(req.tree)
    if isinstance(root, (int, float)):
        return {"optimal_action": "", "action_values": {}, "depth": 0}
    result = solve_minimax(root, depth=req.depth)
    return asdict(result)


@router.post("/regret-matching")
async def post_regret_matching(req: RegretMatchingRequest) -> dict[str, Any]:
    """Find optimal strategy via regret minimization."""
    result = regret_matching(
        payoff_matrix=req.payoff_matrix,
        row_labels=req.row_labels,
        col_labels=req.col_labels,
        iterations=req.iterations,
    )
    return asdict(result)
