"""Regression tests for ``summarize_game``.

Reproduces the production 500 where the list endpoint stopped eager-loading
``SportsGame.plays`` but ``summarize_game`` still had a fallback that lazy-
accessed ``game.plays`` for non-live games. Lazy-loading a SQLAlchemy
relationship inside an async handler raises ``MissingGreenlet`` and turns
every list request into a 500.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import PropertyMock

import pytest

from app.routers.sports.game_helpers import _GameSummaryFlags, summarize_game


class _Team:
    def __init__(self, name: str, abbr: str) -> None:
        self.name = name
        self.abbreviation = abbr
        self.color_light_hex = "#000000"
        self.color_dark_hex = "#ffffff"
        self.color_secondary_light_hex = None
        self.color_secondary_dark_hex = None


class _League:
    def __init__(self, code: str = "MLB") -> None:
        self.code = code


class _ExplodingGame:
    """Stand-in for an unloaded SportsGame. Any access to lazy relationships
    (``plays``, ``team_boxscores``, ``player_boxscores``, ``social_posts``)
    raises, mirroring SQLAlchemy's ``MissingGreenlet`` behavior in async."""

    def __init__(self) -> None:
        self.id = 1
        self.league = _League("MLB")
        self.home_team = _Team("Home", "HOM")
        self.away_team = _Team("Away", "AWY")
        self.home_score = 3
        self.away_score = 2
        self.status = "final"
        self.game_date = datetime(2026, 4, 25, 19, 0, tzinfo=timezone.utc)
        self.local_game_date = self.game_date.date()
        self.season = 2026
        self.season_type = "regular"
        self.scrape_version = 1
        self.last_scraped_at = None
        self.last_ingested_at = None
        self.last_pbp_at = None
        self.last_social_at = None
        self.last_odds_at = None
        self.last_advanced_stats_at = None
        # Odds is eager-loaded by the list endpoint, so it's a real list.
        self.odds = []

    def _explode(self, name: str):  # pragma: no cover - defensive
        raise RuntimeError(
            f"summarize_game must not lazy-access game.{name}; the list "
            f"endpoint does not eager-load it and async lazy loads raise "
            f"MissingGreenlet."
        )

    @property
    def plays(self):
        self._explode("plays")

    @property
    def team_boxscores(self):
        self._explode("team_boxscores")

    @property
    def player_boxscores(self):
        self._explode("player_boxscores")

    @property
    def social_posts(self):
        self._explode("social_posts")


def _flags() -> _GameSummaryFlags:
    return _GameSummaryFlags(
        has_boxscore=True,
        has_player_stats=True,
        has_social=False,
        social_post_count=0,
        has_pbp=False,
        play_count=0,
    )


class TestSummarizeGameDoesNotLazyLoadPlays:
    """Reproduces the production MissingGreenlet 500 on /api/admin/sports/games.

    When the list endpoint passes ``flags`` plus ``latest_play_period=None``
    and ``latest_play_clock=None`` (i.e., a non-live game), ``summarize_game``
    must NOT touch ``game.plays`` — the relationship is unloaded, and any
    access raises ``MissingGreenlet`` inside the async handler."""

    def test_non_live_game_does_not_access_plays(self) -> None:
        game = _ExplodingGame()

        summary = summarize_game(
            game,  # type: ignore[arg-type]
            has_flow=False,
            flags=_flags(),
            latest_play_period=None,
            latest_play_clock=None,
        )

        # Non-live game: no live snapshot, period/clock are None.
        assert summary.live_snapshot is None
        assert summary.current_period is None
        assert summary.game_clock is None
        assert summary.current_period_label is None

    def test_live_game_uses_passed_in_snapshot(self) -> None:
        game = _ExplodingGame()
        game.status = "live"

        summary = summarize_game(
            game,  # type: ignore[arg-type]
            has_flow=False,
            flags=_flags(),
            latest_play_period=7,
            latest_play_clock="2:30",
        )

        assert summary.current_period == 7
        assert summary.game_clock == "2:30"
        assert summary.live_snapshot is not None
        assert summary.live_snapshot.current_period == 7
        assert summary.live_snapshot.game_clock == "2:30"
