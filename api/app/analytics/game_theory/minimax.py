"""Minimax and regret minimization for adversarial in-game decisions.

Provides two complementary approaches:

1. **Minimax with alpha-beta pruning** — For sequential game trees
   (e.g., base-running decisions, bullpen sequencing).
2. **Regret matching (CFR-style)** — For simultaneous-move games
   (e.g., pitch selection, defensive shifts). Both players accumulate
   regret and converge toward a Nash Equilibrium.

Both consume probability data from the existing matchup engine and
simulation system.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

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

    Raises:
        ValueError: If depth limit reached on a non-terminal node without
            terminal child evaluations.
    """
    # True terminal: no available actions
    if not node.actions:
        return "", 0.0

    # Depth cutoff: evaluate using immediate children only
    if depth == 0:
        return _evaluate_at_cutoff(node)

    best_action = ""

    if node.is_maximizer:
        value = -math.inf
        for action, child in node.actions.items():
            if isinstance(child, int | float):
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
            if isinstance(child, int | float):
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


def _evaluate_at_cutoff(node: GameNode) -> tuple[str, float]:
    """Evaluate a node at depth cutoff using only terminal children.

    Raises ValueError if any child is a non-terminal subtree, since
    we have no heuristic evaluation function.
    """
    best_action = ""
    if node.is_maximizer:
        value = -math.inf
        for action, child in node.actions.items():
            if isinstance(child, int | float):
                child_value = float(child)
            else:
                raise ValueError(
                    "Depth limit reached at non-terminal node without terminal evaluations."
                )
            if child_value > value:
                value = child_value
                best_action = action
    else:
        value = math.inf
        for action, child in node.actions.items():
            if isinstance(child, int | float):
                child_value = float(child)
            else:
                raise ValueError(
                    "Depth limit reached at non-terminal node without terminal evaluations."
                )
            if child_value < value:
                value = child_value
                best_action = action
    return best_action, value


def solve_minimax(
    node: GameNode,
    depth: int = 20,
) -> MinimaxResult:
    """Solve a game tree and return structured results.

    Args:
        node: Root of the game tree. Must have at least one action.
        depth: Maximum search depth.

    Returns:
        MinimaxResult with optimal action and per-action values.
    """
    if not node.actions:
        return MinimaxResult(optimal_action="", action_values={}, depth=depth)

    action_values: dict[str, float] = {}

    for action, child in node.actions.items():
        if isinstance(child, int | float):
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
# Regret matching (CFR-style for simultaneous-move games)
# ---------------------------------------------------------------------------


def regret_matching(
    payoff_matrix: list[list[float]],
    row_labels: list[str] | None = None,
    col_labels: list[str] | None = None,
    iterations: int = 10_000,
) -> MinimaxResult:
    """Compute a strategy via counterfactual regret minimization.

    Both players accumulate regret and adjust their strategies toward
    actions they regret not playing. Converges toward a Nash Equilibrium
    of the zero-sum game.

    The row player is the decision-maker whose strategy we output.
    The column player (adversary) also best-responds via regret matching.

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
    if n == 0:
        return MinimaxResult(optimal_action="", action_values={})

    row_labels = row_labels or [f"action_{i}" for i in range(m)]
    col_labels = col_labels or [f"state_{j}" for j in range(n)]

    # Both players track cumulative regret
    row_cumulative_regret = [0.0] * m
    col_cumulative_regret = [0.0] * n
    row_cumulative_strategy = [0.0] * m

    for _t in range(iterations):
        # Current strategies from positive regrets
        row_strategy = _regret_to_strategy(row_cumulative_regret)
        col_strategy = _regret_to_strategy(col_cumulative_regret)

        # Accumulate row player strategy for final average
        for i in range(m):
            row_cumulative_strategy[i] += row_strategy[i]

        # Row player's regret: for each action i, compare payoff of playing i
        # against the current column strategy vs the value of current row strategy
        row_value = sum(
            row_strategy[i] * col_strategy[j] * payoff_matrix[i][j]
            for i in range(m) for j in range(n)
        )
        for i in range(m):
            action_value = sum(col_strategy[j] * payoff_matrix[i][j] for j in range(n))
            row_cumulative_regret[i] += action_value - row_value

        # Column player's regret (minimizer — negate payoffs)
        col_value = row_value  # same game value from column's perspective
        for j in range(n):
            action_value = sum(row_strategy[i] * payoff_matrix[i][j] for i in range(m))
            # Column player wants to minimize, so regret is col_value - action_value
            col_cumulative_regret[j] += col_value - action_value

    # Normalize final strategy
    total = sum(row_cumulative_strategy)
    final_strategy = (
        [c / total for c in row_cumulative_strategy] if total > 0 else [1.0 / m] * m
    )

    # Compute action values: expected payoff of each pure row action vs final col strategy
    final_col_strategy = _regret_to_strategy(col_cumulative_regret)
    action_values = {}
    for i in range(m):
        avg_payoff = sum(final_col_strategy[j] * payoff_matrix[i][j] for j in range(n))
        action_values[row_labels[i]] = round(avg_payoff, 6)

    # Build regret table: regret of deviating to each pure action vs final strategy
    column_values = [
        sum(final_strategy[i] * payoff_matrix[i][j] for i in range(m))
        for j in range(n)
    ]
    regret_table: dict[str, dict[str, float]] = {rl: {} for rl in row_labels}
    for i in range(m):
        for j in range(n):
            regret = payoff_matrix[i][j] - column_values[j]
            regret_table[row_labels[i]][col_labels[j]] = round(regret, 6)

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
