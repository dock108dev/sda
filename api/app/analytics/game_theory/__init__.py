"""Game theory modeling for sports analytics.

Provides strategic optimization on top of the existing prediction engine:

- **Kelly Criterion** — Optimal bet sizing given edge and bankroll.
- **Nash Equilibrium** — Lineup and strategy optimization via zero-sum game solvers.
- **Portfolio Optimization** — Bet diversification using mean-variance analysis.
- **Minimax** — Adversarial decision modeling for in-game strategy.
"""

from .kelly import compute_kelly, compute_kelly_batch, kelly_fraction
from .minimax import minimax, regret_matching, solve_minimax
from .nash import lineup_nash, pitch_selection_nash, solve_zero_sum
from .portfolio import optimize_portfolio
from .types import KellyResult, MinimaxResult, NashEquilibrium, PortfolioResult

__all__ = [
    "compute_kelly",
    "compute_kelly_batch",
    "kelly_fraction",
    "lineup_nash",
    "minimax",
    "MinimaxResult",
    "NashEquilibrium",
    "optimize_portfolio",
    "pitch_selection_nash",
    "PortfolioResult",
    "KellyResult",
    "regret_matching",
    "solve_minimax",
    "solve_zero_sum",
]
