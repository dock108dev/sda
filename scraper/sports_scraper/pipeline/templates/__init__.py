"""Sport-specific narrative fallback template engine.

Each sport module encodes the 3-layer guardrails statically:
  - Identity:   sport-specific voice and terminology
  - Data:       deterministic string interpolation from GameMiniBox
  - Guardrails: output guaranteed to pass validate_blocks.py constraints

No LLM calls are made during rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .mlb import render_blocks as _mlb_blocks
from .nba import render_blocks as _nba_blocks
from .nfl import render_blocks as _nfl_blocks
from .nhl import render_blocks as _nhl_blocks


@dataclass
class GameMiniBox:
    """Structured game data consumed by template rendering."""

    home_team: str
    away_team: str
    home_score: int
    away_score: int
    sport: str
    has_overtime: bool = False
    total_moments: int = 0


def distribute_moments(total: int, n_blocks: int) -> list[list[int]]:
    """Distribute moment indices evenly across n_blocks blocks."""
    if total == 0:
        return [[] for _ in range(n_blocks)]
    sizes = [total // n_blocks] * n_blocks
    for i in range(total % n_blocks):
        sizes[i] += 1
    result: list[list[int]] = []
    start = 0
    for size in sizes:
        result.append(list(range(start, start + size)))
        start += size
    return result


def block_scores(home: int, away: int) -> list[tuple[int, int]]:
    """Return (home, away) score approximations at the end of each of 4 blocks.

    Fractions (0.20, 0.50, 0.75, 1.00) approximate Q1/H1, halftime,
    late-game, and final for NFL/NBA/NHL; close enough for MLB too.
    """
    fractions = (0.20, 0.50, 0.75, 1.00)
    return [(int(home * f), int(away * f)) for f in fractions]


def winner_loser(
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
) -> tuple[str, str]:
    """Return (winner, loser) names; home team wins ties (shouldn't occur for FINAL)."""
    if home_score >= away_score:
        return home_team, away_team
    return away_team, home_team


class TemplateEngine:
    """Renders deterministic fallback narrative blocks from structured game data."""

    @classmethod
    def render(cls, sport: str, mini_box: GameMiniBox) -> list[dict[str, Any]]:
        """Render 4 narrative blocks for the given sport and game.

        Args:
            sport:    League code (NFL, NBA, MLB, NHL).  Case-insensitive.
            mini_box: Structured game data; no LLM calls required.

        Returns:
            List of 4 block dicts compatible with validate_blocks.py.
        """
        chunks = distribute_moments(mini_box.total_moments, 4)
        scores = block_scores(mini_box.home_score, mini_box.away_score)
        s = sport.upper()
        if s == "NFL":
            return _nfl_blocks(mini_box, chunks, scores)
        if s == "NBA":
            return _nba_blocks(mini_box, chunks, scores)
        if s == "MLB":
            return _mlb_blocks(mini_box, chunks, scores)
        if s == "NHL":
            return _nhl_blocks(mini_box, chunks, scores)
        # Generic: reuse NBA template for unsupported sports
        return _nba_blocks(mini_box, chunks, scores)
