"""Minimax and regret minimization for adversarial in-game decisions.

Provides two complementary approaches:

1. **Minimax with alpha-beta pruning** — For sequential game trees
   (e.g., base-running decisions, bullpen sequencing).
2. **Regret matching** — For simultaneous-move games
   (e.g., pitch selection, defensive shifts).

Both consume probability data from the existing matchup engine and
simulation system.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import MinimaxResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Minimax tree search
# ---------------------------------------------------------------------------

@dataclass
class GameNode:
    """A node in a minimax game tree.

    Attributes:
        is_maximizer: True if this node's player is maximizing.
        actions: Mapping from action name to child node or terminal value.
            If the value is a float, it's a terminal node.
            If it's a GameNode, the tree continues.
    """

    is_maximizer: bool
    actions: dict[str, GameNode | float] = field(default_factory=dict)


def minimax(
    node: GameNode,
    depth: int = 20,
    alpha: float = -math.inf,
    beta: float = math.inf,
) -> tuple[str, float]:
    """Run minimax with alpha-beta pruning on a game tree.

    Args:
        node: Root node of the game tree.
        depth: Maximum search depth.
        alpha: Alpha bound (for pruning).
        beta: Beta bound (for pruning).

    Returns:
        Tuple of (best_action, value).
    """
    if not node.actions or depth == 0:
        return "", 0.0

    best_action = ""

    if node.is_maximizer:
        value = -math.inf
        for action, child in node.actions.items():
            if isinstance(child, (int, float)):
                child_value = float(child)
            else:
                _, child_value = minimax(child, depth - 1, alpha, beta)
            if child_value > value:
                value = child_value
                best_action = action
            alpha = max(alpha, value)
            if beta <= alpha:
                break
    else:
        value = math.inf
        for action, child in node.actions.items():
            if isinstance(child, (int, float)):
                child_value = float(child)
            else:
                _, child_value = minimax(child, depth - 1, alpha, beta)
            if child_value < value:
                value = child_value
                best_action = action
            beta = min(beta, value)
            if beta <= alpha:
                break

    return best_action, value


def solve_minimax(
    node: GameNode,
    depth: int = 20,
) -> MinimaxResult:
    """Solve a game tree and return structured results.

    Args:
        node: Root of the game tree.
        depth: Maximum search depth.

    Returns:
        MinimaxResult with optimal action and per-action values.
    """
    action_values: dict[str, float] = {}

    for action, child in node.actions.items():
        if isinstance(child, (int, float)):
            action_values[action] = float(child)
        else:
            _, val = minimax(child, depth - 1)
            action_values[action] = val

    if node.is_maximizer:
        optimal = max(action_values, key=action_values.get)  # type: ignore[arg-type]
    else:
        optimal = min(action_values, key=action_values.get)  # type: ignore[arg-type]

    return MinimaxResult(
        optimal_action=optimal,
        action_values={k: round(v, 6) for k, v in action_values.items()},
        depth=depth,
    )


# ---------------------------------------------------------------------------
# Regret matching (for simultaneous-move games)
# ---------------------------------------------------------------------------


def regret_matching(
    payoff_matrix: list[list[float]],
    row_labels: list[str] | None = None,
    col_labels: list[str] | None = None,
    iterations: int = 10_000,
) -> MinimaxResult:
    """Compute a strategy via regret matching.

    In repeated play, each player adjusts toward actions they regret not
    playing.  Converges to a correlated equilibrium / minimax strategy.

    The row player is the decision-maker whose strategy we want.  The
    column player is the adversary (nature / opponent).

    Args:
        payoff_matrix: M×N payoffs for the row player.
        row_labels: Action labels for the row player.
        col_labels: Action labels for the column player.
        iterations: Number of rounds of regret matching.

    Returns:
        MinimaxResult with the row player's mixed strategy.
    """
    m = len(payoff_matrix)
    if m == 0:
        return MinimaxResult(optimal_action="", action_values={})
    n = len(payoff_matrix[0])

    row_labels = row_labels or [f"action_{i}" for i in range(m)]
    col_labels = col_labels or [f"state_{j}" for j in range(n)]

    cumulative_regret = [0.0] * m
    cumulative_strategy = [0.0] * m
    regret_table: dict[str, dict[str, float]] = {rl: {} for rl in row_labels}

    for t in range(iterations):
        # Current strategy from positive regrets
        strategy = _regret_to_strategy(cumulative_regret)

        # Accumulate strategy
        for i in range(m):
            cumulative_strategy[i] += strategy[i]

        # Opponent plays each column with equal probability (worst-case)
        for j in range(n):
            # Value of current strategy against column j
            current_value = sum(strategy[i] * payoff_matrix[i][j] for i in range(m))

            # Regret for each action
            for i in range(m):
                regret = payoff_matrix[i][j] - current_value
                cumulative_regret[i] += regret / n  # average over opponent actions

    # Normalize final strategy
    total = sum(cumulative_strategy)
    if total > 0:
        final_strategy = [c / total for c in cumulative_strategy]
    else:
        final_strategy = [1.0 / m] * m

    # Compute action values (expected payoff of each pure action vs uniform opponent)
    action_values = {}
    for i in range(m):
        avg_payoff = sum(payoff_matrix[i][j] for j in range(n)) / n
        action_values[row_labels[i]] = round(avg_payoff, 6)

    # Build regret table
    for i in range(m):
        for j in range(n):
            regret_table[row_labels[i]][col_labels[j]] = round(payoff_matrix[i][j], 6)

    strategy_dict = {row_labels[i]: round(final_strategy[i], 6) for i in range(m)}
    optimal = max(strategy_dict, key=strategy_dict.get)  # type: ignore[arg-type]

    return MinimaxResult(
        optimal_action=optimal,
        action_values=action_values,
        regret_table=regret_table,
        strategy=strategy_dict,
    )


def _regret_to_strategy(cumulative_regret: list[float]) -> list[float]:
    """Convert cumulative regrets to a probability distribution."""
    positive = [max(r, 0.0) for r in cumulative_regret]
    total = sum(positive)
    if total > 0:
        return [p / total for p in positive]
    return [1.0 / len(cumulative_regret)] * len(cumulative_regret)
