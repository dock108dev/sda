"""Data structures for game theory module outputs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class KellyResult:
    """Output from Kelly Criterion bet sizing."""

    edge: float
    """Model probability minus implied probability (positive = +EV)."""
    kelly_fraction: float
    """Full Kelly optimal fraction of bankroll to wager."""
    half_kelly: float
    """Half-Kelly (more conservative, commonly used in practice)."""
    quarter_kelly: float
    """Quarter-Kelly (very conservative)."""
    recommended_wager: float
    """Dollar amount to wager (using the selected Kelly variant and bankroll)."""
    bankroll: float
    """Bankroll used for the calculation."""
    model_prob: float
    """Model's estimated true probability of winning."""
    implied_prob: float
    """Implied probability from the sportsbook odds."""
    american_odds: float
    """American odds offered by the sportsbook."""
    decimal_odds: float
    """Decimal odds (payout multiplier including stake)."""
    kelly_variant: str = "half"
    """Which Kelly variant was used for recommended_wager."""


@dataclass
class NashEquilibrium:
    """Output from a two-player zero-sum Nash Equilibrium solver."""

    row_strategy: list[float]
    """Mixed strategy (probability distribution) for the row player."""
    col_strategy: list[float]
    """Mixed strategy (probability distribution) for the column player."""
    game_value: float
    """Expected value of the game for the row player at equilibrium."""
    row_labels: list[str] = field(default_factory=list)
    """Labels for row player's actions."""
    col_labels: list[str] = field(default_factory=list)
    """Labels for column player's actions."""
    iterations: int = 0
    """Number of iterations used (for iterative solvers)."""


@dataclass
class PortfolioAllocation:
    """A single bet within an optimized portfolio."""

    bet_id: str
    label: str
    model_prob: float
    american_odds: float
    edge: float
    weight: float
    """Fraction of bankroll allocated to this bet."""
    expected_return: float


@dataclass
class PortfolioResult:
    """Output from portfolio optimization."""

    allocations: list[PortfolioAllocation]
    total_weight: float
    """Sum of all weights (may be < 1.0 if cash is held)."""
    expected_portfolio_return: float
    portfolio_variance: float
    portfolio_std: float
    sharpe_ratio: float
    """Return per unit of risk (higher is better)."""
    bankroll: float


@dataclass
class MinimaxResult:
    """Output from minimax / regret-minimization solver."""

    optimal_action: str
    """Best action for the maximizing player."""
    action_values: dict[str, float]
    """Expected value of each action."""
    regret_table: dict[str, dict[str, float]] = field(default_factory=dict)
    """Regret accumulated per action per opponent state."""
    strategy: dict[str, float] = field(default_factory=dict)
    """Mixed strategy (probability over actions) after regret minimization."""
    depth: int = 0
    """Search depth used (for tree-based minimax)."""
