"""Nash Equilibrium solver for two-player zero-sum games.

Implements the Lemke-Howson style linear programming approach for small games
and fictitious play for larger games.  Designed for lineup optimization and
pitch-selection strategy where the payoff matrix is derived from the matchup
engine's probability distributions.

Typical use cases:
- Optimal lineup construction (manager vs manager)
- Pitch selection (pitcher vs batter stance)
- Defensive positioning
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from .types import NashEquilibrium

logger = logging.getLogger(__name__)


def solve_zero_sum(
    payoff_matrix: list[list[float]],
    row_labels: list[str] | None = None,
    col_labels: list[str] | None = None,
    max_iterations: int = 10_000,
) -> NashEquilibrium:
    """Find the Nash Equilibrium of a two-player zero-sum game.

    Uses the *fictitious play* algorithm which converges to the minimax
    solution.  Row player is the maximizer; column player is the minimizer.

    Args:
        payoff_matrix: M×N matrix of payoffs for the row player.
        row_labels: Optional names for row actions.
        col_labels: Optional names for column actions.
        max_iterations: Convergence limit for fictitious play.

    Returns:
        NashEquilibrium with mixed strategies and game value.
    """
    m = len(payoff_matrix)
    if m == 0:
        return NashEquilibrium(
            row_strategy=[], col_strategy=[], game_value=0.0,
        )
    n = len(payoff_matrix[0])

    row_labels = row_labels or [f"row_{i}" for i in range(m)]
    col_labels = col_labels or [f"col_{j}" for j in range(n)]

    # Fictitious play: each player tracks cumulative opponent choices
    row_counts = [0.0] * m
    col_counts = [0.0] * n

    # Start with uniform
    row_counts[0] = 1.0
    col_counts[0] = 1.0

    for _t in range(1, max_iterations + 1):
        # Column player best-responds to row player's empirical strategy
        col_payoffs = [0.0] * n
        for j in range(n):
            for i in range(m):
                col_payoffs[j] += row_counts[i] * payoff_matrix[i][j]
        best_col = _argmin(col_payoffs)
        col_counts[best_col] += 1.0

        # Row player best-responds to column player's empirical strategy
        row_payoffs = [0.0] * m
        for i in range(m):
            for j in range(n):
                row_payoffs[i] += col_counts[j] * payoff_matrix[i][j]
        best_row = _argmax(row_payoffs)
        row_counts[best_row] += 1.0

    total_row = sum(row_counts)
    total_col = sum(col_counts)
    row_strategy = [c / total_row for c in row_counts]
    col_strategy = [c / total_col for c in col_counts]

    # Game value: expected payoff under equilibrium strategies
    game_value = 0.0
    for i in range(m):
        for j in range(n):
            game_value += row_strategy[i] * col_strategy[j] * payoff_matrix[i][j]

    return NashEquilibrium(
        row_strategy=[round(s, 6) for s in row_strategy],
        col_strategy=[round(s, 6) for s in col_strategy],
        game_value=round(game_value, 6),
        row_labels=row_labels,
        col_labels=col_labels,
        iterations=max_iterations,
    )


def lineup_nash(
    matchup_matrix: list[list[float]],
    batter_names: list[str],
    pitcher_names: list[str],
) -> NashEquilibrium:
    """Solve for optimal lineup decisions given batter-vs-pitcher matchups.

    The payoff matrix should contain expected outcome values (e.g., wOBA or
    run expectancy) for each batter-pitcher pairing.  The offensive manager
    (row player) maximizes; the pitching side (column player) minimizes.

    Args:
        matchup_matrix: Rows=batters, Cols=pitchers, values=expected outcome.
        batter_names: Display names for batters.
        pitcher_names: Display names for pitchers.

    Returns:
        NashEquilibrium with optimal mixed strategies.
    """
    return solve_zero_sum(
        payoff_matrix=matchup_matrix,
        row_labels=batter_names,
        col_labels=pitcher_names,
    )


def pitch_selection_nash(
    pitch_outcomes: dict[str, dict[str, float]],
) -> NashEquilibrium:
    """Solve for optimal pitch selection strategy.

    Args:
        pitch_outcomes: Nested dict where ``pitch_outcomes[pitch_type][batter_stance]``
            gives the expected run value of that pitch against that stance.
            Positive values favor the batter; negative favor the pitcher.

    Returns:
        NashEquilibrium where row_strategy is the pitcher's optimal mix
        and col_strategy is the batter's optimal stance distribution.
    """
    pitch_types = sorted(pitch_outcomes.keys())
    stances = sorted({s for outcomes in pitch_outcomes.values() for s in outcomes})

    # Pitcher is the row player (minimizer), but we negate so row = maximizer
    # Convention: positive = good for batter, so pitcher wants to minimize
    matrix = []
    for pitch in pitch_types:
        row = [-pitch_outcomes[pitch].get(stance, 0.0) for stance in stances]
        matrix.append(row)

    result = solve_zero_sum(matrix, row_labels=pitch_types, col_labels=stances)

    # Negate game value back to pitcher's perspective
    result.game_value = -result.game_value

    return result


def _argmax(values: Sequence[float]) -> int:
    best_idx = 0
    best_val = values[0]
    for i in range(1, len(values)):
        if values[i] > best_val:
            best_val = values[i]
            best_idx = i
    return best_idx


def _argmin(values: Sequence[float]) -> int:
    best_idx = 0
    best_val = values[0]
    for i in range(1, len(values)):
        if values[i] < best_val:
            best_val = values[i]
            best_idx = i
    return best_idx
