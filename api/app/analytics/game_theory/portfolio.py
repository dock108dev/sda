"""Portfolio optimization for sports betting.

Applies mean-variance optimization (Markowitz) to allocate bankroll across
multiple bets, balancing expected return against variance.  Accounts for
correlation between bets on the same game or related markets.

Builds on top of the Kelly module for individual bet sizing and adds
diversification logic.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .kelly import american_to_decimal
from .types import PortfolioAllocation, PortfolioResult

logger = logging.getLogger(__name__)


def optimize_portfolio(
    bets: list[dict[str, Any]],
    bankroll: float = 1000.0,
    correlation_matrix: list[list[float]] | None = None,
    risk_aversion: float = 2.0,
    max_per_bet: float = 0.20,
    max_total: float = 0.50,
) -> PortfolioResult:
    """Optimize allocation across multiple bets.

    Uses a simplified mean-variance approach: maximize
    ``E[R] - (risk_aversion / 2) * Var[R]`` subject to allocation constraints.

    Args:
        bets: List of dicts, each with:
            - ``bet_id``: Unique identifier.
            - ``label``: Display name.
            - ``model_prob``: Model's estimated true probability.
            - ``american_odds``: Sportsbook odds.
            - ``game_id`` (optional): Used for default correlation.
        bankroll: Total bankroll available.
        correlation_matrix: N×N correlation matrix between bet outcomes.
            If None, bets on the same ``game_id`` get 0.5 correlation,
            others get 0.0.
        risk_aversion: Higher = more conservative (typical range 1-5).
        max_per_bet: Maximum fraction of bankroll on any single bet.
        max_total: Maximum total exposure as fraction of bankroll.

    Returns:
        PortfolioResult with optimized allocations.
    """
    n = len(bets)
    if n == 0:
        return PortfolioResult(
            allocations=[], total_weight=0.0,
            expected_portfolio_return=0.0, portfolio_variance=0.0,
            portfolio_std=0.0, sharpe_ratio=0.0, bankroll=bankroll,
        )

    # Compute per-bet expected return and variance
    returns = []
    variances = []
    edges = []

    for b in bets:
        dec = american_to_decimal(b["american_odds"])
        p = b["model_prob"]
        implied = 1.0 / dec

        # Expected return per dollar wagered: p * (dec - 1) - (1 - p)
        er = p * (dec - 1.0) - (1.0 - p)
        # Variance of a single Bernoulli bet
        var = p * (1.0 - p) * (dec ** 2)

        returns.append(er)
        variances.append(var)
        edges.append(p - implied)

    # Build correlation matrix if not provided
    if correlation_matrix is None:
        correlation_matrix = _default_correlation(bets)

    # Build covariance matrix from variances and correlations
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            cov[i][j] = correlation_matrix[i][j] * math.sqrt(variances[i] * variances[j])

    # Greedy mean-variance optimization with constraints
    # Start with proportional allocation to positive-edge bets
    weights = [0.0] * n
    positive_indices = [i for i in range(n) if edges[i] > 0]

    if positive_indices:
        # Score each bet: expected return / variance (reward-to-risk)
        scores = []
        for i in positive_indices:
            score = returns[i] / max(variances[i], 1e-10)
            scores.append((score, i))
        scores.sort(reverse=True)

        # Allocate proportionally to scores, respecting constraints
        total_score = sum(s for s, _ in scores)
        if total_score > 0:
            for score, i in scores:
                raw_weight = (score / total_score) * max_total
                weights[i] = min(raw_weight, max_per_bet)

        # Iterative adjustment: reduce weights that increase portfolio variance too much
        for _ in range(20):
            port_var = _portfolio_variance(weights, cov)
            port_ret = sum(weights[i] * returns[i] for i in range(n))
            utility = port_ret - (risk_aversion / 2.0) * port_var

            # Try reducing each weight slightly and check if utility improves
            improved = False
            for i in range(n):
                if weights[i] <= 0:
                    continue
                delta = weights[i] * 0.1
                weights[i] -= delta
                new_var = _portfolio_variance(weights, cov)
                new_ret = sum(weights[j] * returns[j] for j in range(n))
                new_utility = new_ret - (risk_aversion / 2.0) * new_var
                if new_utility > utility:
                    improved = True
                    utility = new_utility
                else:
                    weights[i] += delta  # revert
            if not improved:
                break

    # Enforce max_total constraint
    total = sum(weights)
    if total > max_total:
        scale = max_total / total
        weights = [w * scale for w in weights]

    # Build allocations
    allocations = []
    for i in range(n):
        allocations.append(PortfolioAllocation(
            bet_id=bets[i].get("bet_id", f"bet_{i}"),
            label=bets[i].get("label", ""),
            model_prob=bets[i]["model_prob"],
            american_odds=bets[i]["american_odds"],
            edge=round(edges[i], 6),
            weight=round(weights[i], 6),
            expected_return=round(weights[i] * returns[i], 6),
        ))

    total_weight = sum(a.weight for a in allocations)
    port_ret = sum(a.expected_return for a in allocations)
    port_var = _portfolio_variance(weights, cov)
    port_std = math.sqrt(max(port_var, 0.0))
    sharpe = port_ret / port_std if port_std > 0 else 0.0

    return PortfolioResult(
        allocations=allocations,
        total_weight=round(total_weight, 6),
        expected_portfolio_return=round(port_ret, 6),
        portfolio_variance=round(port_var, 6),
        portfolio_std=round(port_std, 6),
        sharpe_ratio=round(sharpe, 4),
        bankroll=bankroll,
    )


def _default_correlation(bets: list[dict]) -> list[list[float]]:
    """Build a default correlation matrix.

    Bets on the same game get 0.5 correlation; others get 0.0.
    """
    n = len(bets)
    corr = [[0.0] * n for _ in range(n)]
    for i in range(n):
        corr[i][i] = 1.0
        game_i = bets[i].get("game_id")
        if game_i is None:
            continue
        for j in range(i + 1, n):
            if bets[j].get("game_id") == game_i:
                corr[i][j] = 0.5
                corr[j][i] = 0.5
    return corr


def _portfolio_variance(weights: list[float], cov: list[list[float]]) -> float:
    """Compute portfolio variance: w' * C * w."""
    n = len(weights)
    var = 0.0
    for i in range(n):
        for j in range(n):
            var += weights[i] * weights[j] * cov[i][j]
    return var
