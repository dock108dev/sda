"""Tests for stale book filtering in EV computation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.routers.fairbet.ev_staleness import filter_stale_books


def _ts(minutes_ago: float = 0) -> datetime:
    """Helper: return a UTC datetime ``minutes_ago`` minutes before a fixed reference."""
    base = datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC)
    return base - timedelta(minutes=minutes_ago)


def _make_bet(books: list[tuple[str, float]]) -> dict:
    """Build a minimal bet dict with books at various staleness levels.

    Each entry in ``books`` is (book_name, minutes_behind_pinnacle).
    Pinnacle is always at minutes_ago=0 (the freshest).
    """
    return {
        "game_id": 1,
        "league_code": "NBA",
        "market_key": "spreads",
        "selection_key": "home",
        "line_value": -3.5,
        "books": [{"book": name, "price": -110, "observed_at": _ts(lag)} for name, lag in books],
    }


KEY = (1, "spreads", "home", -3.5)


class TestFilterStaleBooks:
    """Tests for filter_stale_books()."""

    def test_all_books_fresh(self):
        """No books dropped when all are within the lag threshold."""
        bet = _make_bet(
            [
                ("Pinnacle", 0),
                ("DraftKings", 0.5),
                ("FanDuel", 1.0),
                ("BetMGM", 1.5),
            ]
        )
        bets_map = {KEY: bet}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
        assert len(result[KEY]["books"]) == 4

    def test_one_stale_book_dropped(self):
        """A book 3 minutes behind Pinnacle is dropped; others kept."""
        bet = _make_bet(
            [
                ("Pinnacle", 0),
                ("DraftKings", 0.5),
                ("FanDuel", 1.0),
                ("BetMGM", 3.0),  # 3 min behind → stale
            ]
        )
        bets_map = {KEY: bet}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
        remaining = [b["book"] for b in result[KEY]["books"]]
        assert "BetMGM" not in remaining
        assert len(remaining) == 3
        assert "Pinnacle" in remaining

    def test_no_pinnacle_no_filtering(self):
        """When no sharp book is present, all books are kept."""
        bet = _make_bet(
            [
                ("DraftKings", 0),
                ("FanDuel", 3.0),
                ("BetMGM", 5.0),
            ]
        )
        # Remove Pinnacle from books (none present)
        bets_map = {KEY: bet}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
        assert len(result[KEY]["books"]) == 3

    def test_all_non_sharp_stale(self):
        """All non-sharp books stale → only Pinnacle remains."""
        bet = _make_bet(
            [
                ("Pinnacle", 0),
                ("DraftKings", 5.0),
                ("FanDuel", 4.0),
                ("BetMGM", 3.0),
            ]
        )
        bets_map = {KEY: bet}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
        remaining = [b["book"] for b in result[KEY]["books"]]
        assert remaining == ["Pinnacle"]

    def test_boundary_exactly_at_threshold_kept(self):
        """A book exactly at 120s lag is kept (only >120s is stale)."""
        bet = _make_bet(
            [
                ("Pinnacle", 0),
                ("DraftKings", 2.0),  # exactly 120s → kept
            ]
        )
        bets_map = {KEY: bet}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
        assert len(result[KEY]["books"]) == 2

    def test_boundary_one_second_over_dropped(self):
        """A book at 121s lag is dropped."""
        pinnacle_ts = _ts(0)
        bet = {
            "game_id": 1,
            "league_code": "NBA",
            "market_key": "spreads",
            "selection_key": "home",
            "line_value": -3.5,
            "books": [
                {"book": "Pinnacle", "price": -146, "observed_at": pinnacle_ts},
                {
                    "book": "BetMGM",
                    "price": -110,
                    "observed_at": pinnacle_ts - timedelta(seconds=121),
                },
            ],
        }
        bets_map = {KEY: bet}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})
        remaining = [b["book"] for b in result[KEY]["books"]]
        assert remaining == ["Pinnacle"]

    def test_multiple_bets_mixed_staleness(self):
        """Only stale books in affected bets are dropped; fresh bets untouched."""
        key_a = (1, "spreads", "home", -3.5)
        key_b = (2, "totals", "over", 220.5)

        bet_a = _make_bet(
            [
                ("Pinnacle", 0),
                ("DraftKings", 0.5),
                ("BetMGM", 4.0),  # stale
            ]
        )
        bet_b = _make_bet(
            [
                ("Pinnacle", 0),
                ("FanDuel", 1.0),
                ("Caesars", 1.5),
            ]
        )
        # Fix game_id for bet_b
        bet_b["game_id"] = 2

        bets_map = {key_a: bet_a, key_b: bet_b}
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"})

        # bet_a: BetMGM dropped
        remaining_a = [b["book"] for b in result[key_a]["books"]]
        assert "BetMGM" not in remaining_a
        assert len(remaining_a) == 2

        # bet_b: all kept
        remaining_b = [b["book"] for b in result[key_b]["books"]]
        assert len(remaining_b) == 3

    def test_custom_max_lag(self):
        """Custom max_lag_seconds is respected."""
        bet = _make_bet(
            [
                ("Pinnacle", 0),
                ("DraftKings", 1.0),  # 60s behind
            ]
        )
        bets_map = {KEY: bet}
        # With 30s threshold, DraftKings should be dropped
        result = filter_stale_books(bets_map, sharp_books={"Pinnacle"}, max_lag_seconds=30)
        remaining = [b["book"] for b in result[KEY]["books"]]
        assert remaining == ["Pinnacle"]
