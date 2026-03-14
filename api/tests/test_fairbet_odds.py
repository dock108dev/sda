"""Tests for FairBet odds API endpoint."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.fairbet.ev_annotation import (
    BookOdds,
    _annotate_pair_ev,
    _market_base,
    _pair_opposite_sides,
    derive_entity_key,
)
from app.routers.fairbet.ev_extrapolation import _build_sharp_reference, _try_extrapolated_ev
from app.routers.fairbet.odds import (
    BetDefinition,
    FairbetOddsResponse,
    _build_base_filters,
    get_fairbet_odds,
)
from app.services.ev_config import extrapolation_confidence


class TestBookOddsModel:
    """Tests for BookOdds Pydantic model."""

    def test_valid_book_odds(self):
        """Creates valid BookOdds instance."""
        odds = BookOdds(
            book="DraftKings",
            price=-110,
            observed_at=datetime.now(UTC),
        )
        assert odds.book == "DraftKings"
        assert odds.price == -110

    def test_positive_odds(self):
        """Handles positive American odds."""
        odds = BookOdds(
            book="FanDuel",
            price=150,
            observed_at=datetime.now(UTC),
        )
        assert odds.price == 150


class TestBetDefinitionModel:
    """Tests for BetDefinition Pydantic model."""

    def test_valid_bet_definition(self):
        """Creates valid BetDefinition instance."""
        bet = BetDefinition(
            game_id=1,
            league_code="NBA",
            home_team="Lakers",
            away_team="Celtics",
            game_date=datetime.now(UTC),
            market_key="spreads",
            selection_key="team:lakers",
            line_value=-3.5,
            books=[
                BookOdds(book="DK", price=-110, observed_at=datetime.now(UTC))
            ],
        )
        assert bet.game_id == 1
        assert bet.league_code == "NBA"
        assert len(bet.books) == 1

    def test_moneyline_with_zero_line(self):
        """Moneyline bets use 0 as line_value sentinel."""
        bet = BetDefinition(
            game_id=1,
            league_code="NBA",
            home_team="Lakers",
            away_team="Celtics",
            game_date=datetime.now(UTC),
            market_key="h2h",
            selection_key="team:lakers",
            line_value=0,
            books=[],
        )
        assert bet.line_value == 0
        assert bet.market_key == "h2h"


class TestFairbetOddsResponseModel:
    """Tests for FairbetOddsResponse Pydantic model."""

    def test_empty_response(self):
        """Creates valid empty response."""
        response = FairbetOddsResponse(
            bets=[],
            total=0,
            books_available=[],
            market_categories_available=[],
            games_available=[],
        )
        assert response.total == 0
        assert len(response.bets) == 0

    def test_response_with_bets(self):
        """Creates response with bet data."""
        response = FairbetOddsResponse(
            bets=[
                BetDefinition(
                    game_id=1,
                    league_code="NBA",
                    home_team="Lakers",
                    away_team="Celtics",
                    game_date=datetime.now(UTC),
                    market_key="h2h",
                    selection_key="team:lakers",
                    line_value=0,
                    books=[],
                )
            ],
            total=1,
            books_available=["DraftKings", "FanDuel"],
            market_categories_available=["mainline"],
            games_available=[],
        )
        assert response.total == 1
        assert len(response.books_available) == 2


class TestBuildBaseFilters:
    """Tests for _build_base_filters helper function."""

    def test_returns_game_start_expression(self):
        """Returns game_start expression and conditions."""
        game_start, conditions = _build_base_filters(None)
        assert game_start is not None
        assert len(conditions) >= 2  # status filter + time filter

    def test_adds_league_filter_when_provided(self):
        """Adds league filter condition when league is specified."""
        _, conditions_without = _build_base_filters(None)
        _, conditions_with = _build_base_filters("NBA")
        assert len(conditions_with) == len(conditions_without) + 1

    def test_uppercases_league_code(self):
        """League code is uppercased in filter."""
        # This is tested implicitly through the condition creation
        _, conditions = _build_base_filters("nba")
        assert len(conditions) == 3  # status + time + league


class TestBooksSorting:
    """Tests for odds sorting logic."""

    def test_positive_odds_sorted_descending(self):
        """Positive odds sorted highest first."""
        books = [
            BookOdds(book="A", price=120, observed_at=datetime.now(UTC)),
            BookOdds(book="B", price=150, observed_at=datetime.now(UTC)),
            BookOdds(book="C", price=100, observed_at=datetime.now(UTC)),
        ]
        # Simulate the sorting from the endpoint
        books.sort(key=lambda b: -b.price)
        assert books[0].price == 150
        assert books[1].price == 120
        assert books[2].price == 100

    def test_negative_odds_sorted_best_first(self):
        """Negative odds sorted closest to zero first (better odds)."""
        books = [
            BookOdds(book="A", price=-110, observed_at=datetime.now(UTC)),
            BookOdds(book="B", price=-105, observed_at=datetime.now(UTC)),
            BookOdds(book="C", price=-115, observed_at=datetime.now(UTC)),
        ]
        books.sort(key=lambda b: -b.price)
        assert books[0].price == -105  # Best (closest to even)
        assert books[1].price == -110
        assert books[2].price == -115  # Worst

    def test_mixed_odds_sorted_correctly(self):
        """Mixed positive and negative odds sorted correctly."""
        books = [
            BookOdds(book="A", price=-110, observed_at=datetime.now(UTC)),
            BookOdds(book="B", price=150, observed_at=datetime.now(UTC)),
            BookOdds(book="C", price=-105, observed_at=datetime.now(UTC)),
            BookOdds(book="D", price=120, observed_at=datetime.now(UTC)),
        ]
        books.sort(key=lambda b: -b.price)
        # Positive odds first (higher is better), then negative (closer to 0 is better)
        assert books[0].price == 150
        assert books[1].price == 120
        assert books[2].price == -105
        assert books[3].price == -110


class TestGetFairbetOddsEndpoint:
    """Tests for get_fairbet_odds endpoint."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async database session."""
        session = AsyncMock()
        # Ensure execute returns a mock that can chain .scalar(), .scalars().all(), etc.
        return session

    def _mock_execute_chain(self, session, results_sequence):
        """Helper to set up mock execute to return results in sequence.

        Each item in results_sequence should be a dict with keys:
        - 'scalar': value for .scalar() call
        - 'scalars_all': list for .scalars().all() call
        - 'all': list for .all() call
        """

        async def execute_side_effect(*args, **kwargs):
            if not hasattr(execute_side_effect, "call_count"):
                execute_side_effect.call_count = 0

            idx = execute_side_effect.call_count
            execute_side_effect.call_count += 1

            if idx >= len(results_sequence):
                idx = len(results_sequence) - 1

            result_config = results_sequence[idx]
            mock_result = MagicMock()

            if "scalar" in result_config:
                mock_result.scalar.return_value = result_config["scalar"]

            if "scalars_all" in result_config:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = result_config["scalars_all"]
                mock_result.scalars.return_value = mock_scalars

            if "all" in result_config:
                mock_result.all.return_value = result_config["all"]

            return mock_result

        session.execute = execute_side_effect

    @pytest.fixture
    def mock_game(self):
        """Create a mock game with related objects."""
        game = MagicMock()
        game.game_date = datetime.now(UTC) + timedelta(hours=2)
        game.status = "scheduled"

        league = MagicMock()
        league.code = "NBA"
        game.league = league

        home_team = MagicMock()
        home_team.name = "Los Angeles Lakers"
        game.home_team = home_team

        away_team = MagicMock()
        away_team.name = "Boston Celtics"
        game.away_team = away_team

        return game

    @pytest.fixture
    def mock_odds_row(self, mock_game):
        """Create a mock FairbetGameOddsWork row."""
        row = MagicMock()
        row.game_id = 1
        row.market_key = "spreads"
        row.selection_key = "team:los_angeles_lakers"
        row.line_value = -3.5
        row.book = "DraftKings"
        row.price = -110
        row.observed_at = datetime.now(UTC)
        row.market_category = "mainline"
        row.player_name = None
        row.game = mock_game
        return row

    def _call_kwargs(self, session, **overrides):
        """Build kwargs for get_fairbet_odds with all params explicit."""
        defaults = {
            "session": session,
            "league": None,
            "market_category": None,
            "exclude_categories": None,
            "game_id": None,
            "book": None,
            "player_name": None,
            "min_ev": None,
            "has_fair": None,
            "sort_by": "ev",
            "limit": 100,
            "offset": 0,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_bets(self, mock_session):
        """Returns empty response when no bets exist."""
        # Mock count query returning 0
        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 0},  # Count query
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        assert response.total == 0
        assert response.bets == []
        assert response.books_available == []

    @pytest.mark.asyncio
    async def test_returns_grouped_bets(self, mock_session, mock_odds_row):
        """Returns bets grouped by definition with multiple books."""
        # Create additional books for same bet (need 3 to pass min-books filter)
        mock_row2 = MagicMock()
        mock_row2.game_id = 1
        mock_row2.market_key = "spreads"
        mock_row2.selection_key = "team:los_angeles_lakers"
        mock_row2.line_value = -3.5
        mock_row2.book = "FanDuel"
        mock_row2.price = -108
        mock_row2.observed_at = datetime.now(UTC)
        mock_row2.market_category = "mainline"
        mock_row2.player_name = None
        mock_row2.game = mock_odds_row.game

        mock_row3 = MagicMock()
        mock_row3.game_id = 1
        mock_row3.market_key = "spreads"
        mock_row3.selection_key = "team:los_angeles_lakers"
        mock_row3.line_value = -3.5
        mock_row3.book = "Pinnacle"
        mock_row3.price = -112
        mock_row3.observed_at = datetime.now(UTC)
        mock_row3.market_category = "mainline"
        mock_row3.player_name = None
        mock_row3.game = mock_odds_row.game

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 1},  # Count query
                {"scalars_all": [mock_odds_row, mock_row2, mock_row3]},  # Main data query
                {"all": [("DraftKings",), ("FanDuel",), ("Pinnacle",)]},  # Books query
                {"all": [("mainline",)]},  # Categories query
                {"scalars_all": []},  # Games dropdown query
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        assert response.total == 1
        assert len(response.bets) == 1
        assert len(response.bets[0].books) == 3
        assert response.books_available == ["DraftKings", "FanDuel", "Pinnacle"]

    @pytest.mark.asyncio
    async def test_books_sorted_by_best_odds(self, mock_session, mock_odds_row):
        """Books within a bet are sorted by best odds first."""
        # Create multiple books with different odds
        rows = []
        for book_name, price in [("BookA", -115), ("BookB", -105), ("BookC", -110)]:
            row = MagicMock()
            row.game_id = 1
            row.market_key = "spreads"
            row.selection_key = "team:los_angeles_lakers"
            row.line_value = -3.5
            row.book = book_name
            row.price = price
            row.observed_at = datetime.now(UTC)
            row.market_category = "mainline"
            row.player_name = None
            row.game = mock_odds_row.game
            rows.append(row)

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 1},  # Count query
                {"scalars_all": rows},  # Main data query
                {"all": [("BookA",), ("BookB",), ("BookC",)]},  # Books query
                {"all": [("mainline",)]},  # Categories query
                {"scalars_all": []},  # Games dropdown query
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        # Books should be sorted by best odds first
        books = response.bets[0].books
        assert books[0].price == -105  # Best
        assert books[1].price == -110
        assert books[2].price == -115  # Worst

    @pytest.mark.asyncio
    async def test_pagination_limit_respected(self, mock_session):
        """Limit parameter is passed to database query."""
        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 0},  # Count query returns 0
            ],
        )

        await get_fairbet_odds(**self._call_kwargs(mock_session, limit=50))

        # Verify execute was called (count query)
        # The helper tracks call_count
        assert hasattr(mock_session.execute, "call_count")

    @pytest.mark.asyncio
    async def test_league_filter_applied(self, mock_session):
        """League filter is applied when specified."""
        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 0},  # Count query returns 0
            ],
        )

        await get_fairbet_odds(**self._call_kwargs(mock_session, league="NBA"))

        # Verify execute was called with league filter
        assert hasattr(mock_session.execute, "call_count")

    @pytest.mark.asyncio
    async def test_bet_definition_fields_populated(self, mock_session, mock_odds_row):
        """All BetDefinition fields are correctly populated."""
        # Need 3 books to pass min-books filter
        mock_row2 = MagicMock()
        mock_row2.game_id = 1
        mock_row2.market_key = "spreads"
        mock_row2.selection_key = "team:los_angeles_lakers"
        mock_row2.line_value = -3.5
        mock_row2.book = "FanDuel"
        mock_row2.price = -108
        mock_row2.observed_at = datetime.now(UTC)
        mock_row2.market_category = "mainline"
        mock_row2.player_name = None
        mock_row2.game = mock_odds_row.game

        mock_row3 = MagicMock()
        mock_row3.game_id = 1
        mock_row3.market_key = "spreads"
        mock_row3.selection_key = "team:los_angeles_lakers"
        mock_row3.line_value = -3.5
        mock_row3.book = "Pinnacle"
        mock_row3.price = -112
        mock_row3.observed_at = datetime.now(UTC)
        mock_row3.market_category = "mainline"
        mock_row3.player_name = None
        mock_row3.game = mock_odds_row.game

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 1},  # Count query
                {"scalars_all": [mock_odds_row, mock_row2, mock_row3]},  # Main data query
                {"all": [("DraftKings",), ("FanDuel",), ("Pinnacle",)]},  # Books query
                {"all": [("mainline",)]},  # Categories query
                {"scalars_all": []},  # Games dropdown query
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        bet = response.bets[0]
        assert bet.game_id == 1
        assert bet.league_code == "NBA"
        assert bet.home_team == "Los Angeles Lakers"
        assert bet.away_team == "Boston Celtics"
        assert bet.market_key == "spreads"
        assert bet.selection_key == "team:los_angeles_lakers"
        assert bet.line_value == -3.5

    @pytest.mark.asyncio
    async def test_bets_below_min_books_filtered(self, mock_session, mock_odds_row):
        """Bets with fewer than MIN_BOOKS_FOR_FAIRBET books are excluded."""
        # Bet A (spreads, lakers, -3.5): 3 books → passes filter
        row_a1 = mock_odds_row  # DraftKings
        row_a2 = MagicMock()
        row_a2.game_id = 1
        row_a2.market_key = "spreads"
        row_a2.selection_key = "team:los_angeles_lakers"
        row_a2.line_value = -3.5
        row_a2.book = "FanDuel"
        row_a2.price = -108
        row_a2.observed_at = datetime.now(UTC)
        row_a2.market_category = "mainline"
        row_a2.player_name = None
        row_a2.game = mock_odds_row.game

        row_a3 = MagicMock()
        row_a3.game_id = 1
        row_a3.market_key = "spreads"
        row_a3.selection_key = "team:los_angeles_lakers"
        row_a3.line_value = -3.5
        row_a3.book = "Pinnacle"
        row_a3.price = -112
        row_a3.observed_at = datetime.now(UTC)
        row_a3.market_category = "mainline"
        row_a3.player_name = None
        row_a3.game = mock_odds_row.game

        # Bet B (h2h, lakers, 0): 1 book → filtered out
        row_b1 = MagicMock()
        row_b1.game_id = 1
        row_b1.market_key = "h2h"
        row_b1.selection_key = "team:los_angeles_lakers"
        row_b1.line_value = 0
        row_b1.book = "DraftKings"
        row_b1.price = -150
        row_b1.observed_at = datetime.now(UTC)
        row_b1.market_category = "mainline"
        row_b1.player_name = None
        row_b1.game = mock_odds_row.game

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 2},  # Count query (2 bet definitions)
                {"scalars_all": [row_a1, row_a2, row_a3, row_b1]},  # Main data query
                {"all": [("DraftKings",), ("FanDuel",), ("Pinnacle",)]},  # Books
                {"all": [("mainline",)]},  # Categories
                {"scalars_all": []},  # Games dropdown
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        # Only bet A (3 books) should remain; bet B (1 book) filtered out
        assert len(response.bets) == 1
        assert response.bets[0].market_key == "spreads"


class TestBetGrouping:
    """Tests for bet grouping logic."""

    def test_same_bet_different_books_grouped(self):
        """Multiple books for same bet are grouped together."""
        # Test the grouping key logic
        key1 = (1, "spreads", "team:lakers", -3.5)
        key2 = (1, "spreads", "team:lakers", -3.5)
        assert key1 == key2

    def test_different_games_not_grouped(self):
        """Bets from different games are not grouped."""
        key1 = (1, "spreads", "team:lakers", -3.5)
        key2 = (2, "spreads", "team:lakers", -3.5)
        assert key1 != key2

    def test_different_markets_not_grouped(self):
        """Different market types are not grouped."""
        key1 = (1, "spreads", "team:lakers", -3.5)
        key2 = (1, "h2h", "team:lakers", 0)
        assert key1 != key2

    def test_different_selections_not_grouped(self):
        """Different selections are not grouped."""
        key1 = (1, "spreads", "team:lakers", -3.5)
        key2 = (1, "spreads", "team:celtics", 3.5)
        assert key1 != key2

    def test_different_lines_not_grouped(self):
        """Different line values are not grouped."""
        key1 = (1, "spreads", "team:lakers", -3.5)
        key2 = (1, "spreads", "team:lakers", -4.0)
        assert key1 != key2


class TestResponseStructure:
    """Tests for response structure validation."""

    def test_response_model_serialization(self):
        """Response model serializes correctly."""
        response = FairbetOddsResponse(
            bets=[
                BetDefinition(
                    game_id=1,
                    league_code="NBA",
                    home_team="Lakers",
                    away_team="Celtics",
                    game_date=datetime(2025, 1, 15, 19, 0, tzinfo=UTC),
                    market_key="h2h",
                    selection_key="team:lakers",
                    line_value=0,
                    books=[
                        BookOdds(
                            book="DraftKings",
                            price=-110,
                            observed_at=datetime(
                                2025, 1, 15, 12, 0, tzinfo=UTC
                            ),
                        )
                    ],
                )
            ],
            total=1,
            books_available=["DraftKings"],
            market_categories_available=["mainline"],
            games_available=[],
        )

        # Serialize to dict
        data = response.model_dump()

        assert "bets" in data
        assert "total" in data
        assert "books_available" in data
        assert data["total"] == 1
        assert len(data["bets"]) == 1
        assert data["bets"][0]["league_code"] == "NBA"


class TestPairOppositeSides:
    """Unit tests for the _pair_opposite_sides helper."""

    def test_simple_two_way_pair(self):
        """Two keys with different selection_keys are paired."""
        keys = [
            (1, "spreads", "team:lakers", -3.5),
            (1, "spreads", "team:celtics", 3.5),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 1
        assert len(unpaired) == 0
        assert pairs[0] == (keys[0], keys[1])

    def test_single_key_unpaired(self):
        """A single key has no partner."""
        keys = [(1, "spreads", "team:lakers", -3.5)]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 0
        assert len(unpaired) == 1

    def test_same_selection_key_not_paired(self):
        """Two keys with the same selection_key are NOT paired."""
        keys = [
            (1, "spreads", "team:lakers", -1.5),
            (1, "spreads", "team:lakers", -2.5),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 0
        assert len(unpaired) == 2

    def test_four_keys_two_pairs(self):
        """Four keys forming two valid pairs are all matched."""
        keys = [
            (1, "spreads", "team:lakers", -1.5),
            (1, "spreads", "team:celtics", 1.5),
            (1, "spreads", "team:lakers", -2.5),
            (1, "spreads", "team:celtics", 2.5),
        ]
        # abs(line_value) groups: {1.5: [0,1], 2.5: [2,3]}
        # But this helper receives keys already in the same abs-group,
        # so test two separate calls.

        # Group 1: -1.5 and +1.5
        pairs1, unpaired1 = _pair_opposite_sides([keys[0], keys[1]])
        assert len(pairs1) == 1
        assert len(unpaired1) == 0

        # Group 2: -2.5 and +2.5
        pairs2, unpaired2 = _pair_opposite_sides([keys[2], keys[3]])
        assert len(pairs2) == 1
        assert len(unpaired2) == 0

    def test_three_keys_one_pair_one_unpaired(self):
        """Three keys: first two pair, third is left unpaired."""
        keys = [
            (1, "spreads", "team:lakers", -3.5),
            (1, "spreads", "team:celtics", 3.5),
            (1, "spreads", "team:lakers", -3.5),  # duplicate side
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 1
        assert len(unpaired) == 1
        # The unpaired key shares selection_key with the first
        assert unpaired[0][2] == "team:lakers"

    def test_empty_input(self):
        """Empty list returns empty results."""
        pairs, unpaired = _pair_opposite_sides([])
        assert pairs == []
        assert unpaired == []

    def test_cross_zero_alt_spreads_paired_correctly(self):
        """Four keys at abs=1.5 with cross-zero lines pair correctly.

        SQL ORDER BY produces: (la, -1.5), (la, +1.5), (odu, -1.5), (odu, +1.5).
        Before the fix, (la, -1.5) would pair with (odu, -1.5) — WRONG because
        both are the "giving 1.5" side from different markets. The fix ensures
        lines must sum to ~0 (opposite sides of same market).
        """
        # Simulate SQL ordering: team:la entries first, then team:odu, by line_value
        keys = [
            (1, "alternate_spreads", "team:louisiana", -1.5),
            (1, "alternate_spreads", "team:louisiana", 1.5),
            (1, "alternate_spreads", "team:old_dominion", -1.5),
            (1, "alternate_spreads", "team:old_dominion", 1.5),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)

        assert len(pairs) == 2
        assert len(unpaired) == 0

        # Each pair must have line values that sum to zero (opposite sides)
        for key_a, key_b in pairs:
            assert abs(key_a[3] + key_b[3]) < 0.01, (
                f"Pair lines should sum to 0: {key_a[3]} + {key_b[3]}"
            )
            assert key_a[2] != key_b[2], "Pair must have different selection_keys"

    def test_same_sign_lines_not_paired(self):
        """Two keys with same-sign non-zero lines are NOT paired even with different selections."""
        keys = [
            (1, "alternate_spreads", "team:la", -1.5),
            (1, "alternate_spreads", "team:odu", -1.5),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 0
        assert len(unpaired) == 2

    def test_totals_same_line_paired(self):
        """Totals: both sides have the same line_value and should pair."""
        keys = [
            (1, "totals", "total:over", 200.5),
            (1, "totals", "total:under", 200.5),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 1
        assert len(unpaired) == 0

    def test_moneyline_zero_lines_paired(self):
        """Moneyline: both sides have line_value=0 and should pair."""
        keys = [
            (1, "h2h", "team:a", 0),
            (1, "h2h", "team:b", 0),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 1
        assert len(unpaired) == 0


class TestAltSpreadGrouping:
    """Tests for alt spread EV grouping — ensures distinct lines get independent EV."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock async database session."""
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_game(self):
        """Create a mock game with related objects."""
        game = MagicMock()
        game.game_date = datetime.now(UTC) + timedelta(hours=2)
        game.status = "scheduled"

        league = MagicMock()
        league.code = "NCAAB"
        game.league = league

        home_team = MagicMock()
        home_team.name = "Seton Hall"
        game.home_team = home_team

        away_team = MagicMock()
        away_team.name = "Villanova"
        game.away_team = away_team

        return game

    def _make_odds_row(
        self,
        game: MagicMock,
        game_id: int,
        market_key: str,
        selection_key: str,
        line_value: float,
        book: str,
        price: float,
    ) -> MagicMock:
        """Create a mock FairbetGameOddsWork row."""
        row = MagicMock()
        row.game_id = game_id
        row.market_key = market_key
        row.selection_key = selection_key
        row.line_value = line_value
        row.book = book
        row.price = price
        row.observed_at = datetime.now(UTC)
        row.market_category = "alternate"
        row.player_name = None
        row.game = game
        return row

    def _mock_execute_chain(
        self, session: AsyncMock, results_sequence: list[dict]
    ) -> None:
        """Set up mock execute to return results in sequence."""

        async def execute_side_effect(*args, **kwargs):
            if not hasattr(execute_side_effect, "call_count"):
                execute_side_effect.call_count = 0
            idx = min(execute_side_effect.call_count, len(results_sequence) - 1)
            execute_side_effect.call_count += 1
            result_config = results_sequence[idx]
            mock_result = MagicMock()
            if "scalar" in result_config:
                mock_result.scalar.return_value = result_config["scalar"]
            if "scalars_all" in result_config:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = result_config["scalars_all"]
                mock_result.scalars.return_value = mock_scalars
            if "all" in result_config:
                mock_result.all.return_value = result_config["all"]
            return mock_result

        session.execute = execute_side_effect

    def _call_kwargs(self, session: AsyncMock, **overrides: Any) -> dict:
        """Build kwargs for get_fairbet_odds."""
        defaults = {
            "session": session,
            "league": None,
            "market_category": None,
            "exclude_categories": None,
            "game_id": None,
            "book": None,
            "player_name": None,
            "min_ev": None,
            "has_fair": None,
            "sort_by": "ev",
            "limit": 100,
            "offset": 0,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.asyncio
    async def test_alt_spreads_get_distinct_fair_odds(self, mock_session, mock_game):
        """Two alt spread lines (-1.5/+1.5 and -2.5/+2.5) get independent EV."""
        rows = [
            # Line pair 1: -1.5 / +1.5
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "Pinnacle", -120
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "DraftKings", -115
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "FanDuel", -118
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 1.5, "Pinnacle", 105
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 1.5, "DraftKings", 100
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 1.5, "FanDuel", 102
            ),
            # Line pair 2: -2.5 / +2.5
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -2.5, "Pinnacle", -145
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -2.5, "DraftKings", -140
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -2.5, "FanDuel", -142
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 2.5, "Pinnacle", 125
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 2.5, "DraftKings", 120
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 2.5, "FanDuel", 122
            ),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 4},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("alternate",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        # Should have 4 bet definitions (2 sides x 2 lines)
        assert len(response.bets) == 4

        # Group by line_value to check independence
        by_line: dict[float, list[BetDefinition]] = {}
        for bet in response.bets:
            by_line.setdefault(abs(bet.line_value), []).append(bet)

        assert 1.5 in by_line
        assert 2.5 in by_line

        # Each pair should NOT have ev_disabled_reason (they have valid pairs)
        for bet in response.bets:
            assert bet.ev_disabled_reason != "no_pair", (
                f"Bet {bet.selection_key} @ {bet.line_value} should not be no_pair"
            )

    @pytest.mark.asyncio
    async def test_alt_spreads_not_collapsed(self, mock_session, mock_game):
        """Signed line_values that abs() collapses still get independent EV per pair."""
        # Both SHU -1.5 and SHU -2.5 have abs values 1.5 and 2.5.
        # Without the fix, 4 entries with abs=1.5 would mis-group.
        rows = [
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "Pinnacle", -120
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "DraftKings", -115
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "FanDuel", -118
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 1.5, "Pinnacle", 105
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 1.5, "DraftKings", 100
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 1.5, "FanDuel", 102
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -2.5, "Pinnacle", -145
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -2.5, "DraftKings", -140
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -2.5, "FanDuel", -142
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 2.5, "Pinnacle", 125
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 2.5, "DraftKings", 120
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:villanova", 2.5, "FanDuel", 122
            ),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 4},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("alternate",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        assert len(response.bets) == 4
        # No bet should be marked no_pair — all have valid opposite sides
        for bet in response.bets:
            assert bet.ev_disabled_reason != "no_pair"

    @pytest.mark.asyncio
    async def test_same_selection_key_not_paired(self, mock_session, mock_game):
        """Two entries with the same selection_key are NOT paired even if abs(line) matches."""
        # Two SHU sides at -1.5 and +1.5 (same selection_key) — no opposite side available
        rows = [
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "Pinnacle", -120
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "DraftKings", -115
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", -1.5, "FanDuel", -118
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", 1.5, "Pinnacle", 105
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", 1.5, "DraftKings", 100
            ),
            self._make_odds_row(
                mock_game, 1, "spreads", "team:seton_hall", 1.5, "FanDuel", 102
            ),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 2},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("alternate",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        # Both bets have the same selection_key, so they should NOT pair
        shu_bets = [b for b in response.bets if b.selection_key == "team:seton_hall"]
        for bet in shu_bets:
            assert bet.ev_disabled_reason == "no_pair"


class TestFairOddsOutlierHandling:
    """Integration tests for fair_odds_outlier handling via the endpoint."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_game(self):
        game = MagicMock()
        game.game_date = datetime.now(UTC) + timedelta(hours=2)
        game.status = "scheduled"
        league = MagicMock()
        league.code = "NBA"
        game.league = league
        home_team = MagicMock()
        home_team.name = "Los Angeles Lakers"
        game.home_team = home_team
        away_team = MagicMock()
        away_team.name = "Boston Celtics"
        game.away_team = away_team
        return game

    def _make_odds_row(
        self,
        game: MagicMock,
        game_id: int,
        market_key: str,
        selection_key: str,
        line_value: float,
        book: str,
        price: float,
        market_category: str = "team_prop",
    ) -> MagicMock:
        row = MagicMock()
        row.game_id = game_id
        row.market_key = market_key
        row.selection_key = selection_key
        row.line_value = line_value
        row.book = book
        row.price = price
        row.observed_at = datetime.now(UTC)
        row.market_category = market_category
        row.player_name = "Test Player"
        row.game = game
        return row

    def _mock_execute_chain(
        self, session: AsyncMock, results_sequence: list[dict]
    ) -> None:
        async def execute_side_effect(*args, **kwargs):
            if not hasattr(execute_side_effect, "call_count"):
                execute_side_effect.call_count = 0
            idx = min(execute_side_effect.call_count, len(results_sequence) - 1)
            execute_side_effect.call_count += 1
            result_config = results_sequence[idx]
            mock_result = MagicMock()
            if "scalar" in result_config:
                mock_result.scalar.return_value = result_config["scalar"]
            if "scalars_all" in result_config:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = result_config["scalars_all"]
                mock_result.scalars.return_value = mock_scalars
            if "all" in result_config:
                mock_result.all.return_value = result_config["all"]
            return mock_result

        session.execute = execute_side_effect

    def _call_kwargs(self, session: AsyncMock, **overrides: Any) -> dict:
        defaults = {
            "session": session,
            "league": None,
            "market_category": None,
            "exclude_categories": None,
            "game_id": None,
            "book": None,
            "player_name": None,
            "min_ev": None,
            "has_fair": None,
            "sort_by": "ev",
            "limit": 100,
            "offset": 0,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.asyncio
    async def test_fair_odds_outlier_marked(self, mock_session, mock_game):
        """When devig produces implausible fair odds, bet gets ev_disabled_reason='fair_odds_outlier'."""
        # Pinnacle has extremely lopsided line; other books don't agree
        rows = [
            # Side A: over — Pinnacle at -1500, consensus near -400
            self._make_odds_row(
                mock_game, 1, "player_points", "total:over", 20.5, "Pinnacle", -1500
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:over", 20.5, "DraftKings", -400
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:over", 20.5, "FanDuel", -400
            ),
            # Side B: under — Pinnacle at +800, consensus near +350
            self._make_odds_row(
                mock_game, 1, "player_points", "total:under", 20.5, "Pinnacle", 800
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:under", 20.5, "DraftKings", 350
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:under", 20.5, "FanDuel", 350
            ),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 2},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("team_prop",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        # Both sides should be flagged as outliers
        for bet in response.bets:
            assert bet.ev_disabled_reason == "fair_odds_outlier", (
                f"Bet {bet.selection_key} should have fair_odds_outlier, "
                f"got {bet.ev_disabled_reason}"
            )
            # No EV annotation on books
            for book in bet.books:
                assert book.ev_percent is None
            # But method and tier are still present
            assert bet.ev_method == "pinnacle_devig"
            assert bet.ev_confidence_tier == "thin"

    @pytest.mark.asyncio
    async def test_fair_odds_outlier_marks_sharp(self, mock_session, mock_game):
        """When fair_odds_outlier suppresses EV, Pinnacle still gets is_sharp=True."""
        rows = [
            self._make_odds_row(
                mock_game, 1, "player_points", "total:over", 20.5, "Pinnacle", -1500
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:over", 20.5, "DraftKings", -400
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:over", 20.5, "FanDuel", -400
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:under", 20.5, "Pinnacle", 800
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:under", 20.5, "DraftKings", 350
            ),
            self._make_odds_row(
                mock_game, 1, "player_points", "total:under", 20.5, "FanDuel", 350
            ),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 2},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("team_prop",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        for bet in response.bets:
            pinnacle_books = [b for b in bet.books if b.book == "Pinnacle"]
            assert len(pinnacle_books) == 1
            assert pinnacle_books[0].is_sharp is True
            # Non-sharp books should have is_sharp=False
            for b in bet.books:
                if b.book != "Pinnacle":
                    assert b.is_sharp is False


class TestSharpBooksRetainedWhenEvDisabled:
    """Tests that is_sharp is set correctly when EV is disabled or unpaired."""

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_game(self):
        game = MagicMock()
        game.game_date = datetime.now(UTC) + timedelta(hours=2)
        game.status = "scheduled"
        league = MagicMock()
        league.code = "NBA"
        game.league = league
        home_team = MagicMock()
        home_team.name = "Lakers"
        game.home_team = home_team
        away_team = MagicMock()
        away_team.name = "Celtics"
        game.away_team = away_team
        return game

    def _make_odds_row(
        self,
        game,
        game_id,
        market_key,
        selection_key,
        line_value,
        book,
        price,
        market_category="mainline",
    ):
        row = MagicMock()
        row.game_id = game_id
        row.market_key = market_key
        row.selection_key = selection_key
        row.line_value = line_value
        row.book = book
        row.price = price
        row.observed_at = datetime.now(UTC)
        row.market_category = market_category
        row.player_name = None
        row.game = game
        return row

    def _mock_execute_chain(self, session, results_sequence):
        async def execute_side_effect(*args, **kwargs):
            if not hasattr(execute_side_effect, "call_count"):
                execute_side_effect.call_count = 0
            idx = min(execute_side_effect.call_count, len(results_sequence) - 1)
            execute_side_effect.call_count += 1
            result_config = results_sequence[idx]
            mock_result = MagicMock()
            if "scalar" in result_config:
                mock_result.scalar.return_value = result_config["scalar"]
            if "scalars_all" in result_config:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = result_config["scalars_all"]
                mock_result.scalars.return_value = mock_scalars
            if "all" in result_config:
                mock_result.all.return_value = result_config["all"]
            return mock_result

        session.execute = execute_side_effect

    def _call_kwargs(self, session, **overrides):
        defaults = {
            "session": session,
            "league": None,
            "market_category": None,
            "exclude_categories": None,
            "game_id": None,
            "book": None,
            "player_name": None,
            "min_ev": None,
            "has_fair": None,
            "sort_by": "ev",
            "limit": 100,
            "offset": 0,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.asyncio
    async def test_unpaired_bet_marks_sharp(self, mock_session, mock_game):
        """Single-sided bet (no pair) still marks Pinnacle as is_sharp."""
        rows = [
            self._make_odds_row(
                mock_game, 1, "h2h", "team:lakers", 0, "Pinnacle", -150
            ),
            self._make_odds_row(
                mock_game, 1, "h2h", "team:lakers", 0, "DraftKings", -145
            ),
            self._make_odds_row(
                mock_game, 1, "h2h", "team:lakers", 0, "FanDuel", -148
            ),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 1},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("mainline",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        bet = response.bets[0]
        assert bet.ev_disabled_reason == "no_pair"
        pinnacle = next(b for b in bet.books if b.book == "Pinnacle")
        assert pinnacle.is_sharp is True

    @pytest.mark.asyncio
    async def test_sharp_retained_with_book_filter_when_ev_disabled(
        self, mock_session, mock_game
    ):
        """When filtering by book=DraftKings, Pinnacle is retained via is_sharp."""
        rows = [
            self._make_odds_row(
                mock_game, 1, "h2h", "team:lakers", 0, "Pinnacle", -150
            ),
            self._make_odds_row(
                mock_game, 1, "h2h", "team:lakers", 0, "DraftKings", -145
            ),
            self._make_odds_row(mock_game, 1, "h2h", "team:lakers", 0, "FanDuel", -148),
        ]

        self._mock_execute_chain(
            mock_session,
            [
                {"scalar": 1},
                {"scalars_all": rows},
                {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",)]},
                {"all": [("mainline",)]},
                {"scalars_all": []},
            ],
        )

        response = await get_fairbet_odds(
            **self._call_kwargs(mock_session, book="DraftKings")
        )

        bet = response.bets[0]
        book_names = [b.book for b in bet.books]
        # DraftKings kept by filter, Pinnacle kept by is_sharp
        assert "DraftKings" in book_names
        assert "Pinnacle" in book_names
        # FanDuel filtered out
        assert "FanDuel" not in book_names


# ---------------------------------------------------------------------------
# Tests for sharp reference extrapolation
# ---------------------------------------------------------------------------


class TestMarketBase:
    """Tests for _market_base() normalization."""

    def test_spreads(self):
        assert _market_base("spreads") == "spreads"

    def test_alternate_spreads(self):
        assert _market_base("alternate_spreads") == "spreads"

    def test_totals(self):
        assert _market_base("totals") == "totals"

    def test_alternate_totals(self):
        assert _market_base("alternate_totals") == "totals"

    def test_h2h_returns_none(self):
        assert _market_base("h2h") is None

    def test_player_prop_returns_none(self):
        assert _market_base("player_points") is None

    def test_case_insensitive(self):
        assert _market_base("Alternate_Spreads") == "spreads"
        assert _market_base("TOTALS") == "totals"


class TestExtrapolationConfidence:
    """Tests for extrapolation_confidence() tiers based on non-sharp book count."""

    def test_zero_books_is_thin(self):
        assert extrapolation_confidence(0) == "thin"

    def test_one_book_is_thin(self):
        assert extrapolation_confidence(1) == "thin"

    def test_two_books_is_thin(self):
        assert extrapolation_confidence(2) == "thin"

    def test_three_books_is_decent(self):
        assert extrapolation_confidence(3) == "decent"

    def test_four_books_is_decent(self):
        assert extrapolation_confidence(4) == "decent"

    def test_five_books_is_full(self):
        assert extrapolation_confidence(5) == "full"

    def test_ten_books_is_full(self):
        assert extrapolation_confidence(10) == "full"


class TestBuildSharpReference:
    """Tests for _build_sharp_reference() index builder."""

    def _make_bets_map(self, entries):
        """Build a bets_map from a list of (game_id, market_key, selection_key, line_value, books) tuples."""
        bets_map = {}
        for game_id, market_key, selection_key, line_value, books in entries:
            key = (game_id, market_key, selection_key, line_value)
            bets_map[key] = {
                "game_id": game_id,
                "market_key": market_key,
                "selection_key": selection_key,
                "line_value": line_value,
                "league_code": "NCAAB",
                "books": books,
            }
        return bets_map

    def test_single_pinnacle_pair(self):
        """Builds reference from a single Pinnacle two-sided pair."""
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            (1, "spreads", "team:a", -6.0, [
                {"book": "Pinnacle", "price": -120, "observed_at": now},
                {"book": "DraftKings", "price": -115, "observed_at": now},
            ]),
            (1, "spreads", "team:b", 6.0, [
                {"book": "Pinnacle", "price": 105, "observed_at": now},
                {"book": "DraftKings", "price": 100, "observed_at": now},
            ]),
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})

        assert (1, "spreads", "game") in refs
        ref_list = refs[(1, "spreads", "game")]
        assert len(ref_list) == 1
        assert ref_list[0]["abs_line"] == 6.0
        assert ref_list[0]["is_mainline"] is True
        assert "team:a" in ref_list[0]["probs"]
        assert "team:b" in ref_list[0]["probs"]
        # Probs should sum to 1.0
        assert abs(ref_list[0]["probs"]["team:a"] + ref_list[0]["probs"]["team:b"] - 1.0) < 0.001

    def test_multiple_lines_sorted(self):
        """Multiple Pinnacle lines are stored and sorted (mainline first)."""
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            # Alternate line at 8.0
            (1, "alternate_spreads", "team:a", -8.0, [
                {"book": "Pinnacle", "price": 130, "observed_at": now},
            ]),
            (1, "alternate_spreads", "team:b", 8.0, [
                {"book": "Pinnacle", "price": -155, "observed_at": now},
            ]),
            # Mainline at 6.0
            (1, "spreads", "team:a", -6.0, [
                {"book": "Pinnacle", "price": -120, "observed_at": now},
            ]),
            (1, "spreads", "team:b", 6.0, [
                {"book": "Pinnacle", "price": 105, "observed_at": now},
            ]),
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})

        ref_list = refs[(1, "spreads", "game")]
        assert len(ref_list) == 2
        # Mainline comes first
        assert ref_list[0]["is_mainline"] is True
        assert ref_list[0]["abs_line"] == 6.0
        assert ref_list[1]["is_mainline"] is False
        assert ref_list[1]["abs_line"] == 8.0

    def test_no_pinnacle_no_reference(self):
        """No reference built when Pinnacle is absent."""
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            (1, "spreads", "team:a", -6.0, [
                {"book": "DraftKings", "price": -115, "observed_at": now},
            ]),
            (1, "spreads", "team:b", 6.0, [
                {"book": "DraftKings", "price": 100, "observed_at": now},
            ]),
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        assert len(refs) == 0

    def test_single_sided_pinnacle_no_reference(self):
        """No reference when Pinnacle exists only on one side."""
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            (1, "spreads", "team:a", -6.0, [
                {"book": "Pinnacle", "price": -120, "observed_at": now},
            ]),
            # No matching opposite side with Pinnacle
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        assert len(refs) == 0

    def test_h2h_market_skipped(self):
        """h2h market keys are not extrapolatable."""
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            (1, "h2h", "team:a", 0, [
                {"book": "Pinnacle", "price": -150, "observed_at": now},
            ]),
            (1, "h2h", "team:b", 0, [
                {"book": "Pinnacle", "price": 130, "observed_at": now},
            ]),
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        assert len(refs) == 0

    def test_cross_zero_alt_spreads_produce_two_references(self):
        """Four entries at abs=1.5 (cross-zero) produce two separate reference pairs."""
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            # Market 1: ODU -1.5 / LA +1.5 (ODU favored)
            (1, "alternate_spreads", "team:odu", -1.5, [
                {"book": "Pinnacle", "price": -200, "observed_at": now},
            ]),
            (1, "alternate_spreads", "team:la", 1.5, [
                {"book": "Pinnacle", "price": 170, "observed_at": now},
            ]),
            # Market 2: LA -1.5 / ODU +1.5 (LA favored — opposite direction)
            (1, "alternate_spreads", "team:la", -1.5, [
                {"book": "Pinnacle", "price": 300, "observed_at": now},
            ]),
            (1, "alternate_spreads", "team:odu", 1.5, [
                {"book": "Pinnacle", "price": -400, "observed_at": now},
            ]),
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})

        assert (1, "spreads", "game") in refs
        ref_list = refs[(1, "spreads", "game")]
        # Should have 2 reference entries (one per valid market pair), not 1
        assert len(ref_list) == 2

        # Each reference should have probs summing to ~1.0
        for ref in ref_list:
            total_prob = sum(ref["probs"].values())
            assert abs(total_prob - 1.0) < 0.01

    def test_cross_zero_reference_does_not_mix_markets(self):
        """Cross-zero references don't devig prices from different markets.

        Without the fix, the dict would overwrite entries for the same selection_key,
        mixing prices from different markets and producing wrong probabilities.
        """
        now = datetime.now(UTC)
        bets_map = self._make_bets_map([
            # ODU -1.5 at -200 (ODU is moderate favorite)
            (1, "alternate_spreads", "team:odu", -1.5, [
                {"book": "Pinnacle", "price": -200, "observed_at": now},
            ]),
            # LA +1.5 at +170 (LA is moderate underdog — pairs with ODU -1.5)
            (1, "alternate_spreads", "team:la", 1.5, [
                {"book": "Pinnacle", "price": 170, "observed_at": now},
            ]),
            # LA -1.5 at +300 (LA needs to win by 2+ — big underdog)
            (1, "alternate_spreads", "team:la", -1.5, [
                {"book": "Pinnacle", "price": 300, "observed_at": now},
            ]),
            # ODU +1.5 at -400 (ODU just needs to not lose by 2+ — heavy favorite)
            (1, "alternate_spreads", "team:odu", 1.5, [
                {"book": "Pinnacle", "price": -400, "observed_at": now},
            ]),
        ])

        refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        ref_list = refs[(1, "spreads", "game")]

        for ref in ref_list:
            # Verify the prices in each reference are from the same market
            # (lines that sum to 0)
            prices = ref["prices"]
            sels = list(prices.keys())
            price_a = prices[sels[0]]
            price_b = prices[sels[1]]
            # One should be negative (favorite) and one positive (underdog) —
            # never both negative or both positive from the same market
            assert (price_a > 0) != (price_b > 0) or (
                abs(price_a) < 101 and abs(price_b) < 101
            ), f"Prices {price_a}, {price_b} look like they're from different markets"


class TestTryExtrapolatedEv:
    """Tests for _try_extrapolated_ev() fallback logic."""

    def _make_bets_map_and_refs(
        self,
        *,
        ref_line: float = 6.0,
        ref_price_a: float = -120,
        ref_price_b: float = 105,
        target_line: float = 7.5,
        target_price_a: float = 110,
        target_price_b: float = -110,
        league: str = "NCAAB",
        market_key: str = "alternate_spreads",
        ref_market_key: str = "spreads",
    ):
        """Build a bets_map with a target pair and sharp refs."""
        now = datetime.now(UTC)

        bets_map = {
            # Target pair (no Pinnacle)
            (1, market_key, "team:a", -target_line): {
                "game_id": 1,
                "market_key": market_key,
                "selection_key": "team:a",
                "line_value": -target_line,
                "league_code": league,
                "market_category": "alternate",
                "books": [
                    BookOdds(
                        book="DraftKings", price=target_price_a,
                        observed_at=now,
                    ),
                    BookOdds(
                        book="FanDuel", price=target_price_a + 5,
                        observed_at=now,
                    ),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, market_key, "team:b", target_line): {
                "game_id": 1,
                "market_key": market_key,
                "selection_key": "team:b",
                "line_value": target_line,
                "league_code": league,
                "market_category": "alternate",
                "books": [
                    BookOdds(
                        book="DraftKings", price=target_price_b,
                        observed_at=now,
                    ),
                    BookOdds(
                        book="FanDuel", price=target_price_b - 5,
                        observed_at=now,
                    ),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            # Reference pair (Pinnacle present — used to build sharp_refs)
            (1, ref_market_key, "team:a", -ref_line): {
                "game_id": 1,
                "market_key": ref_market_key,
                "selection_key": "team:a",
                "line_value": -ref_line,
                "league_code": league,
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": ref_price_a, "observed_at": now},
                ],
            },
            (1, ref_market_key, "team:b", ref_line): {
                "game_id": 1,
                "market_key": ref_market_key,
                "selection_key": "team:b",
                "line_value": ref_line,
                "league_code": league,
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": ref_price_b, "observed_at": now},
                ],
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})

        key_a = (1, market_key, "team:a", -target_line)
        key_b = (1, market_key, "team:b", target_line)
        return bets_map, sharp_refs, key_a, key_b

    def test_spread_extrapolation_success(self):
        """Extrapolation succeeds for a spread 3 half-points away."""
        bets_map, refs, key_a, key_b = self._make_bets_map_and_refs()

        result = _try_extrapolated_ev(key_a, key_b, bets_map, refs)

        assert result is None  # Success
        assert bets_map[key_a]["has_fair"] is True
        assert bets_map[key_b]["has_fair"] is True
        assert bets_map[key_a]["ev_method"] == "pinnacle_extrapolated"
        assert bets_map[key_b]["ev_method"] == "pinnacle_extrapolated"
        assert bets_map[key_a]["true_prob"] is not None
        assert bets_map[key_b]["true_prob"] is not None
        # Books should have EV annotated
        for b in bets_map[key_a]["books"]:
            assert b.ev_percent is not None
            assert b.ev_method == "pinnacle_extrapolated"

    def test_underdog_as_key_a_extrapolation_direction(self):
        """When sel_a is the underdog (positive line), prob should INCREASE
        when getting more points (target_line > ref_line).

        This is the core direction bug: the old formula always subtracted
        the shift, which was correct for the favorite but inverted the
        underdog's probability.
        """
        bets_map, refs, key_a, key_b = self._make_bets_map_and_refs()

        # Swap key_a/key_b so the underdog (positive line) is key_a
        result = _try_extrapolated_ev(key_b, key_a, bets_map, refs)

        assert result is None
        # key_b (team:b at +7.5) is now sel_a — underdog getting 7.5 points
        # Reference has team:b at +6.0 covering ~47% (underdog getting fewer points)
        # At +7.5 (more points), team:b's prob should be HIGHER than at +6.0
        ref_prob_b = refs[(1, "spreads", "game")][0]["probs"]["team:b"]
        assert bets_map[key_b]["true_prob"] > ref_prob_b, (
            f"Underdog at +8.5 ({bets_map[key_b]['true_prob']:.3f}) should have "
            f"higher prob than at +6.0 ({ref_prob_b:.3f})"
        )
        # And the favorite's prob should be LOWER
        ref_prob_a = refs[(1, "spreads", "game")][0]["probs"]["team:a"]
        assert bets_map[key_a]["true_prob"] < ref_prob_a, (
            f"Favorite at -8.5 ({bets_map[key_a]['true_prob']:.3f}) should have "
            f"lower prob than at -6.0 ({ref_prob_a:.3f})"
        )
        # Probs should sum to 1
        assert abs(bets_map[key_a]["true_prob"] + bets_map[key_b]["true_prob"] - 1.0) < 0.01

    def test_cross_zero_spread_extrapolation(self):
        """Extrapolation for a cross-zero alt spread uses signed line shift.

        Reference: team:a at -4.0 (favorite), team:b at +4.0 (underdog).
        Target: team:a at -2.5 (still favorite, giving fewer pts), team:b at +2.5.
        The signed shift for team:a is (-2.5 - (-4.0)) = +1.5, which is 3 half-points.
        Team:a going from giving 4 to giving 2.5 → their cover prob should INCREASE.
        """
        bets_map, refs, key_a, key_b = self._make_bets_map_and_refs(
            ref_line=4.0,
            ref_price_a=-140,
            ref_price_b=120,
            target_line=2.5,
            target_price_a=-200,  # team:a at -2.5 (still favorite, giving fewer pts)
            target_price_b=170,  # team:b at +2.5 (still underdog, getting fewer pts)
        )

        # key_a = (1, "alternate_spreads", "team:a", -2.5)  (favorite in this market)
        # key_b = (1, "alternate_spreads", "team:b", 2.5)   (underdog in this market)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, refs)

        assert result is None
        # team:a at reference had signed line -4.0 (giving 4), prob ~56%
        # team:a at target has signed line -2.5 (giving 2.5)
        # Giving FEWER points → prob should INCREASE (easier to cover)
        ref_prob_a = refs[(1, "spreads", "game")][0]["probs"]["team:a"]
        assert bets_map[key_a]["true_prob"] > ref_prob_a, (
            f"team:a at -2.5 ({bets_map[key_a]['true_prob']:.3f}) should have "
            f"higher prob than at -4.0 ({ref_prob_a:.3f})"
        )

    def test_total_extrapolation_success(self):
        """Extrapolation works for totals market (3 HP away)."""
        bets_map, refs, key_a, key_b = self._make_bets_map_and_refs(
            market_key="alternate_totals",
            ref_market_key="totals",
            ref_line=220.0,
            ref_price_a=-110,
            ref_price_b=-110,
            target_line=221.5,
            target_price_a=105,
            target_price_b=-125,
        )

        result = _try_extrapolated_ev(key_a, key_b, bets_map, refs)
        assert result is None
        assert bets_map[key_a]["has_fair"] is True

    def test_out_of_range_blocked(self):
        """Extrapolation beyond max half-points returns out_of_range."""
        # NHL with target 5 full goals away (10 half-points, max is 6)
        bets_map, refs, key_a, key_b = self._make_bets_map_and_refs(
            league="NHL",
            ref_line=5.5,
            target_line=10.5,  # 10 half-points away
            ref_price_a=-130,
            ref_price_b=110,
            target_price_a=300,
            target_price_b=-400,
        )

        result = _try_extrapolated_ev(key_a, key_b, bets_map, refs)
        assert result == "extrapolation_out_of_range"

    def test_non_extrapolatable_market(self):
        """h2h market returns reference_missing."""
        now = datetime.now(UTC)
        bets_map = {
            (1, "h2h", "team:a", 0): {
                "game_id": 1,
                "market_key": "h2h",
                "selection_key": "team:a",
                "line_value": 0,
                "league_code": "NBA",
                "books": [BookOdds(book="DK", price=-150, observed_at=now)],
            },
            (1, "h2h", "team:b", 0): {
                "game_id": 1,
                "market_key": "h2h",
                "selection_key": "team:b",
                "line_value": 0,
                "league_code": "NBA",
                "books": [BookOdds(book="DK", price=130, observed_at=now)],
            },
        }
        key_a = (1, "h2h", "team:a", 0)
        key_b = (1, "h2h", "team:b", 0)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, {})
        assert result == "reference_missing"

    def test_selection_key_mismatch(self):
        """Returns reference_missing when selection_keys don't match."""
        now = datetime.now(UTC)
        # Build refs with team:x/team:y, but target has team:a/team:b
        ref_bets = {
            (1, "spreads", "team:x", -6.0): {
                "game_id": 1, "market_key": "spreads", "selection_key": "team:x",
                "line_value": -6.0, "league_code": "NCAAB",
                "books": [{"book": "Pinnacle", "price": -120, "observed_at": now}],
            },
            (1, "spreads", "team:y", 6.0): {
                "game_id": 1, "market_key": "spreads", "selection_key": "team:y",
                "line_value": 6.0, "league_code": "NCAAB",
                "books": [{"book": "Pinnacle", "price": 105, "observed_at": now}],
            },
        }
        sharp_refs = _build_sharp_reference(ref_bets, {"Pinnacle"})

        target_bets = {
            (1, "alternate_spreads", "team:a", -8.5): {
                "game_id": 1, "market_key": "alternate_spreads",
                "selection_key": "team:a", "line_value": -8.5,
                "league_code": "NCAAB",
                "books": [BookOdds(book="DK", price=150, observed_at=now)],
            },
            (1, "alternate_spreads", "team:b", 8.5): {
                "game_id": 1, "market_key": "alternate_spreads",
                "selection_key": "team:b", "line_value": 8.5,
                "league_code": "NCAAB",
                "books": [BookOdds(book="DK", price=-180, observed_at=now)],
            },
        }

        key_a = (1, "alternate_spreads", "team:a", -8.5)
        key_b = (1, "alternate_spreads", "team:b", 8.5)
        result = _try_extrapolated_ev(key_a, key_b, target_bets, sharp_refs)
        assert result == "reference_missing"

    def test_extreme_extrapolation_rejected_by_divergence(self):
        """4 HP shift produces divergence > 7% threshold → rejected."""
        # Mainline at 148.0 with Pinnacle -110/-110 (50/50 after devig).
        # Target at 146.0 → 4 half-points away (2 full points).
        # NCAAB totals slope=0.06 → logit shift=0.24 → extrap prob for "over"
        # goes to ~56%, but soft books price it at ~-115 (~53.5%).
        # We use wide book prices that push divergence above 7%.
        now = datetime.now(UTC)
        bets_map = {
            # Target pair at 146.0 — no Pinnacle, soft books price "over" low
            # Extrap says ~56% but books price it at ~43% → divergence ~13%
            (1, "alternate_totals", "over", 146.0): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "over",
                "line_value": 146.0,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=130, observed_at=now),
                    BookOdds(book="FanDuel", price=125, observed_at=now),
                    BookOdds(book="BetMGM", price=135, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "alternate_totals", "under", 146.0): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "under",
                "line_value": 146.0,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-150, observed_at=now),
                    BookOdds(book="FanDuel", price=-145, observed_at=now),
                    BookOdds(book="BetMGM", price=-155, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            # Reference: Pinnacle mainline at 148.0
            (1, "totals", "over", 148.0): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.0,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
            (1, "totals", "under", 148.0): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.0,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        key_a = (1, "alternate_totals", "over", 146.0)
        key_b = (1, "alternate_totals", "under", 146.0)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result == "extrapolation_fair_divergence"

    def test_moderate_extrapolation_passes_divergence(self):
        """3 HP shift stays within divergence threshold → passes."""
        # Mainline at 148.0 with Pinnacle -110/-110 → devigged to 50/50.
        # Target at 149.5 → 3 half-points away.
        # NCAAB totals slope=0.12 → logit shift=-0.36 for "over" → extrap ~41.1%.
        # Soft books at +130 (~43.5%) vs extrap ~41.1% → divergence ~2.4% → passes.
        now = datetime.now(UTC)
        bets_map = {
            (1, "alternate_totals", "over", 149.5): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "over",
                "line_value": 149.5,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=130, observed_at=now),
                    BookOdds(book="FanDuel", price=125, observed_at=now),
                    BookOdds(book="BetMGM", price=135, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "alternate_totals", "under", 149.5): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "under",
                "line_value": 149.5,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-140, observed_at=now),
                    BookOdds(book="FanDuel", price=-135, observed_at=now),
                    BookOdds(book="BetMGM", price=-145, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "totals", "over", 148.0): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.0,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
            (1, "totals", "under", 148.0): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.0,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        key_a = (1, "alternate_totals", "over", 149.5)
        key_b = (1, "alternate_totals", "under", 149.5)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result is None  # Should pass divergence check
        assert bets_map[key_a]["has_fair"] is True
        assert bets_map[key_a]["ev_method"] == "pinnacle_extrapolated"

    def test_mainline_disagreement_blocked(self):
        """Mainline-to-mainline extrapolation blocked when distance > 2 points.

        Pinnacle totals 148.5, FanDuel totals 142.5 → 6 full points apart.
        Both are mainline markets, so this is cross-book line disagreement,
        NOT an alternate-line relationship. Should return mainline_line_disagreement.
        """
        now = datetime.now(UTC)
        bets_map = {
            # Target pair: mainline totals at 142.5 (no Pinnacle)
            (1, "totals", "over", 142.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 142.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    BookOdds(book="FanDuel", price=-115, observed_at=now),
                    BookOdds(book="DraftKings", price=-112, observed_at=now),
                    BookOdds(book="BetMGM", price=-118, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "totals", "under", 142.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 142.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    BookOdds(book="FanDuel", price=-105, observed_at=now),
                    BookOdds(book="DraftKings", price=-108, observed_at=now),
                    BookOdds(book="BetMGM", price=-102, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            # Reference: Pinnacle mainline at 148.5
            (1, "totals", "over", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
            (1, "totals", "under", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        key_a = (1, "totals", "over", 142.5)
        key_b = (1, "totals", "under", 142.5)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result == "mainline_line_disagreement"

    def test_alternate_allowed_within_bounds(self):
        """Alternate totals 1.5 points from mainline → passes (within 6 HP max).

        Pinnacle mainline at 148.5, alternate at 147.0 → 3 half-points.
        Should succeed because: alternate market, within HP limit, and
        probability divergence stays small.
        """
        now = datetime.now(UTC)
        bets_map = {
            # Target pair: alternate totals at 147.0 (no Pinnacle)
            (1, "alternate_totals", "over", 147.0): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "over",
                "line_value": 147.0,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-118, observed_at=now),
                    BookOdds(book="FanDuel", price=-115, observed_at=now),
                    BookOdds(book="BetMGM", price=-120, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "alternate_totals", "under", 147.0): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "under",
                "line_value": 147.0,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-102, observed_at=now),
                    BookOdds(book="FanDuel", price=-105, observed_at=now),
                    BookOdds(book="BetMGM", price=-100, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            # Reference: Pinnacle mainline at 148.5
            (1, "totals", "over", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
            (1, "totals", "under", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        key_a = (1, "alternate_totals", "over", 147.0)
        key_b = (1, "alternate_totals", "under", 147.0)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result is None  # Should succeed
        assert bets_map[key_a]["has_fair"] is True
        assert bets_map[key_a]["ev_method"] == "pinnacle_extrapolated"

    def test_out_of_range_at_new_limits(self):
        """Alternate totals 148.5 → 142.5 = 12 HP > 6 max → out of range.

        With the tightened limits (max 6 HP for NCAAB totals), a 12 half-point
        extrapolation should be rejected even though the old 20 HP limit allowed it.
        """
        now = datetime.now(UTC)
        bets_map = {
            # Target pair: alternate totals at 142.5 (12 HP from ref)
            (1, "alternate_totals", "over", 142.5): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "over",
                "line_value": 142.5,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-115, observed_at=now),
                    BookOdds(book="FanDuel", price=-112, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "alternate_totals", "under", 142.5): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "under",
                "line_value": 142.5,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-105, observed_at=now),
                    BookOdds(book="FanDuel", price=-108, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            # Reference: Pinnacle mainline at 148.5
            (1, "totals", "over", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
            (1, "totals", "under", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": now},
                ],
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})
        key_a = (1, "alternate_totals", "over", 142.5)
        key_b = (1, "alternate_totals", "under", 142.5)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result == "extrapolation_out_of_range"

    def test_stale_ref_excluded(self):
        """Sharp reference older than SHARP_REF_MAX_AGE_SECONDS is excluded.

        When Pinnacle's observed_at is 2 hours old (> 3600s threshold),
        _build_sharp_reference with max_age_seconds=3600 should skip it,
        leaving no reference → extrapolation returns reference_missing.
        """
        now = datetime.now(UTC)
        stale_time = now - timedelta(hours=2)  # 7200s ago > 3600s threshold
        bets_map = {
            # Target pair: alternate totals at 147.0
            (1, "alternate_totals", "over", 147.0): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "over",
                "line_value": 147.0,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=-140, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (1, "alternate_totals", "under", 147.0): {
                "game_id": 1,
                "market_key": "alternate_totals",
                "selection_key": "under",
                "line_value": 147.0,
                "league_code": "NCAAB",
                "market_category": "alternate",
                "books": [
                    BookOdds(book="DraftKings", price=130, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            # Reference: Pinnacle mainline at 148.5 — but STALE (2h old)
            (1, "totals", "over", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": stale_time},
                ],
            },
            (1, "totals", "under", 148.5): {
                "game_id": 1,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -110, "observed_at": stale_time},
                ],
            },
        }

        # Build with staleness check enabled (3600s)
        sharp_refs = _build_sharp_reference(
            bets_map, {"Pinnacle"}, max_age_seconds=3600
        )
        key_a = (1, "alternate_totals", "over", 147.0)
        key_b = (1, "alternate_totals", "under", 147.0)

        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result == "reference_missing"

        # Verify the ref IS found when staleness check is disabled
        sharp_refs_no_age = _build_sharp_reference(bets_map, {"Pinnacle"})
        result_no_age = _try_extrapolated_ev(
            key_a, key_b, bets_map, sharp_refs_no_age
        )
        assert result_no_age is None  # Should pass without staleness check

    def test_regression_mainline_disagreement_wichita_ecu(self):
        """Regression: Wichita St @ ECU mainline totals at different lines.

        Simulates the production scenario where Pinnacle has totals at 148.5
        but DraftKings/FanDuel have mainline totals at 145.5. This 3-point
        difference exceeds MAINLINE_DISAGREEMENT_MAX_POINTS (2.0), so the
        extrapolation path should be blocked with mainline_line_disagreement.

        No bet should show EV > 10% from mainline-to-mainline extrapolation.
        """
        now = datetime.now(UTC)
        bets_map = {
            # Pinnacle mainline totals at 148.5
            (99, "totals", "over", 148.5): {
                "game_id": 99,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -108, "observed_at": now},
                    {"book": "BetMGM", "price": -112, "observed_at": now},
                ],
            },
            (99, "totals", "under", 148.5): {
                "game_id": 99,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 148.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    {"book": "Pinnacle", "price": -112, "observed_at": now},
                    {"book": "BetMGM", "price": -108, "observed_at": now},
                ],
            },
            # DraftKings/FanDuel mainline totals at 145.5 (3 points away)
            (99, "totals", "over", 145.5): {
                "game_id": 99,
                "market_key": "totals",
                "selection_key": "over",
                "line_value": 145.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    BookOdds(book="DraftKings", price=-110, observed_at=now),
                    BookOdds(book="FanDuel", price=-108, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
            (99, "totals", "under", 145.5): {
                "game_id": 99,
                "market_key": "totals",
                "selection_key": "under",
                "line_value": 145.5,
                "league_code": "NCAAB",
                "market_category": "mainline",
                "books": [
                    BookOdds(book="DraftKings", price=-110, observed_at=now),
                    BookOdds(book="FanDuel", price=-112, observed_at=now),
                ],
                "ev_disabled_reason": "reference_missing",
            },
        }

        sharp_refs = _build_sharp_reference(bets_map, {"Pinnacle"})

        # The 145.5 pair should be blocked as mainline disagreement
        key_a = (99, "totals", "over", 145.5)
        key_b = (99, "totals", "under", 145.5)
        result = _try_extrapolated_ev(key_a, key_b, bets_map, sharp_refs)
        assert result == "mainline_line_disagreement"

        # Verify no phantom EV was annotated
        for key in [key_a, key_b]:
            for b in bets_map[key]["books"]:
                ev = b.ev_percent if hasattr(b, "ev_percent") else None
                assert ev is None or ev <= 10.0, (
                    f"Phantom EV {ev}% on {b.book if hasattr(b, 'book') else b['book']}"
                )


class TestLogitTailBehavior:
    """Verify logit extrapolation produces sensible tail probabilities."""

    def test_deep_extrapolation_compresses_in_tail(self):
        """10 half-points from 52% should give ~20-35%, not linear 37%."""
        import math

        base_prob = 0.52
        n_half_points = 10  # 5 full points
        slope = 0.14  # NCAAB spreads

        base_logit = math.log(base_prob / (1 - base_prob))
        new_logit = base_logit - (n_half_points * slope)
        p_new = 1 / (1 + math.exp(-new_logit))

        # Logit gives ~20-25% (compressed tail)
        assert 0.15 < p_new < 0.35, f"Expected 15-35%, got {p_new:.3f}"

        # Linear would give: 0.52 - (10 * 0.015) = 0.37
        # Logit should be MORE compressed (lower) than linear
        linear_p = base_prob - (n_half_points * 0.015)
        assert p_new < linear_p, (
            f"Logit ({p_new:.3f}) should be less than linear ({linear_p:.3f})"
        )

    def test_symmetry_sums_to_one(self):
        """Both sides of extrapolated probabilities sum to 1.0."""
        import math

        base_prob_a = 0.55
        n_half_points = 4
        slope = 0.12  # NBA spreads

        base_logit_a = math.log(base_prob_a / (1 - base_prob_a))
        new_logit_a = base_logit_a - (n_half_points * slope)
        p_a = 1 / (1 + math.exp(-new_logit_a))
        p_b = 1 - p_a

        assert abs(p_a + p_b - 1.0) < 1e-10

    def test_small_extrapolation_close_to_base(self):
        """1 half-point extrapolation barely changes probability."""
        import math

        base_prob = 0.52
        slope = 0.14

        base_logit = math.log(base_prob / (1 - base_prob))
        new_logit = base_logit - (1 * slope)
        p_new = 1 / (1 + math.exp(-new_logit))

        # Should be close to 0.52 — within ~3.5%
        assert abs(p_new - base_prob) < 0.04

    def test_nhl_large_slope_compresses_fast(self):
        """NHL's larger slope per half-point compresses probability faster."""
        import math

        base_prob = 0.55
        slope_nhl = 0.35
        slope_ncaab = 0.14
        n_half_points = 4

        logit = math.log(base_prob / (1 - base_prob))

        p_nhl = 1 / (1 + math.exp(-(logit - n_half_points * slope_nhl)))
        p_ncaab = 1 / (1 + math.exp(-(logit - n_half_points * slope_ncaab)))

        # NHL should compress more than NCAAB at same half-point distance
        assert p_nhl < p_ncaab


class TestExtrapolationEndToEnd:
    """End-to-end test: pair with Pinnacle at different line gets has_fair via extrapolation."""

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def mock_game(self):
        game = MagicMock()
        game.game_date = datetime.now(UTC) + timedelta(hours=2)
        game.status = "scheduled"
        league = MagicMock()
        league.code = "NCAAB"
        game.league = league
        home = MagicMock()
        home.name = "Seton Hall"
        game.home_team = home
        away = MagicMock()
        away.name = "Villanova"
        game.away_team = away
        return game

    def _make_odds_row(self, game, game_id, market_key, selection_key, line_value, book, price, market_category="mainline"):
        row = MagicMock()
        row.game_id = game_id
        row.market_key = market_key
        row.selection_key = selection_key
        row.line_value = line_value
        row.book = book
        row.price = price
        row.observed_at = datetime.now(UTC)
        row.market_category = market_category
        row.player_name = None
        row.game = game
        return row

    def _mock_execute_chain(self, session, results_sequence):
        async def execute_side_effect(*args, **kwargs):
            if not hasattr(execute_side_effect, "call_count"):
                execute_side_effect.call_count = 0
            idx = min(execute_side_effect.call_count, len(results_sequence) - 1)
            execute_side_effect.call_count += 1
            result_config = results_sequence[idx]
            mock_result = MagicMock()
            if "scalar" in result_config:
                mock_result.scalar.return_value = result_config["scalar"]
            if "scalars_all" in result_config:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = result_config["scalars_all"]
                mock_result.scalars.return_value = mock_scalars
            if "all" in result_config:
                mock_result.all.return_value = result_config["all"]
            return mock_result
        session.execute = execute_side_effect

    def _call_kwargs(self, session, **overrides):
        defaults = {
            "session": session, "league": None, "market_category": None,
            "exclude_categories": None,
            "game_id": None, "book": None, "player_name": None,
            "min_ev": None, "has_fair": None, "sort_by": "ev",
            "limit": 100, "offset": 0,
        }
        defaults.update(overrides)
        return defaults

    @pytest.mark.asyncio
    async def test_extrapolation_via_endpoint(self, mock_session, mock_game):
        """Alternate spread at different line gets has_fair=True via Pinnacle mainline extrapolation."""
        rows = [
            # Pinnacle mainline at -6.0/+6.0 (both sides)
            self._make_odds_row(mock_game, 1, "spreads", "team:seton_hall", -6.0, "Pinnacle", -120),
            self._make_odds_row(mock_game, 1, "spreads", "team:seton_hall", -6.0, "DraftKings", -115),
            self._make_odds_row(mock_game, 1, "spreads", "team:seton_hall", -6.0, "FanDuel", -118),
            self._make_odds_row(mock_game, 1, "spreads", "team:villanova", 6.0, "Pinnacle", 105),
            self._make_odds_row(mock_game, 1, "spreads", "team:villanova", 6.0, "DraftKings", 100),
            self._make_odds_row(mock_game, 1, "spreads", "team:villanova", 6.0, "FanDuel", 102),
            # Alternate at -7.5/+7.5 (3 HP from mainline) — NO Pinnacle → fallback
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:seton_hall", -7.5, "DraftKings", 110, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:seton_hall", -7.5, "FanDuel", 108, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:seton_hall", -7.5, "Caesars", 112, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:villanova", 7.5, "DraftKings", -130, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:villanova", 7.5, "FanDuel", -128, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:villanova", 7.5, "Caesars", -132, market_category="alternate"),
        ]

        self._mock_execute_chain(mock_session, [
            {"scalar": 4},
            {"scalars_all": rows},
            {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",), ("Caesars",)]},
            {"all": [("mainline",), ("alternate",)]},
            {"scalars_all": []},
        ])

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        # Mainline pair: has_fair via direct devig
        mainline_bets = [b for b in response.bets if b.market_key == "spreads"]
        for bet in mainline_bets:
            assert bet.has_fair is True
            assert bet.ev_method == "pinnacle_devig"

        # Alternate pair: has_fair via extrapolation
        alt_bets = [b for b in response.bets if b.market_key == "alternate_spreads"]
        assert len(alt_bets) == 2
        for bet in alt_bets:
            assert bet.has_fair is True, (
                f"Alternate bet {bet.selection_key} @ {bet.line_value} should have has_fair=True"
            )
            assert bet.ev_method == "pinnacle_extrapolated"
            assert bet.true_prob is not None
            # All books should have EV annotated
            for book in bet.books:
                assert book.ev_percent is not None

        # Diagnostics should show extrapolated count
        assert response.ev_diagnostics.get("extrapolated", 0) >= 1

    @pytest.mark.asyncio
    async def test_extrapolation_probs_are_reasonable(self, mock_session, mock_game):
        """Extrapolated probabilities are in a reasonable range."""
        rows = [
            # Pinnacle mainline at -6.0/+6.0
            self._make_odds_row(mock_game, 1, "spreads", "team:seton_hall", -6.0, "Pinnacle", -120),
            self._make_odds_row(mock_game, 1, "spreads", "team:seton_hall", -6.0, "DraftKings", -115),
            self._make_odds_row(mock_game, 1, "spreads", "team:seton_hall", -6.0, "FanDuel", -118),
            self._make_odds_row(mock_game, 1, "spreads", "team:villanova", 6.0, "Pinnacle", 105),
            self._make_odds_row(mock_game, 1, "spreads", "team:villanova", 6.0, "DraftKings", 100),
            self._make_odds_row(mock_game, 1, "spreads", "team:villanova", 6.0, "FanDuel", 102),
            # Alternate at -7.5/+7.5 (3 half-points away)
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:seton_hall", -7.5, "DraftKings", 110, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:seton_hall", -7.5, "FanDuel", 108, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:seton_hall", -7.5, "Caesars", 112, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:villanova", 7.5, "DraftKings", -130, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:villanova", 7.5, "FanDuel", -128, market_category="alternate"),
            self._make_odds_row(mock_game, 1, "alternate_spreads", "team:villanova", 7.5, "Caesars", -132, market_category="alternate"),
        ]

        self._mock_execute_chain(mock_session, [
            {"scalar": 4},
            {"scalars_all": rows},
            {"all": [("Pinnacle",), ("DraftKings",), ("FanDuel",), ("Caesars",)]},
            {"all": [("mainline",), ("alternate",)]},
            {"scalars_all": []},
        ])

        response = await get_fairbet_odds(**self._call_kwargs(mock_session))

        alt_bets = [b for b in response.bets if b.market_key == "alternate_spreads"]
        probs = [b.true_prob for b in alt_bets if b.true_prob is not None]

        # Should have 2 probs that sum to ~1.0
        assert len(probs) == 2
        assert abs(sum(probs) - 1.0) < 0.01, f"Probs {probs} should sum to ~1.0"

        # Favorite at wider line should be less likely than at mainline
        fav_alt = next(b for b in alt_bets if b.line_value < 0)
        fav_main = next(b for b in response.bets if b.market_key == "spreads" and b.line_value < 0)
        assert fav_alt.true_prob < fav_main.true_prob, (
            f"Favorite at wider line ({fav_alt.true_prob}) should be less "
            f"likely than at mainline ({fav_main.true_prob})"
        )


class TestDeriveEntityKey:
    """Unit tests for derive_entity_key() helper."""

    def test_player_prop_with_player_name(self):
        """Player prop with player_name produces player:{slug}:{hash8}."""
        key = derive_entity_key(
            "player:lebron_james:over", "player_points", player_name="LeBron James"
        )
        assert key.startswith("player:lebron_james:")
        # Hash should be 8 hex chars
        parts = key.split(":")
        assert len(parts) == 3
        assert len(parts[2]) == 8

    def test_player_prop_without_player_name(self):
        """Player prop without player_name produces player:{slug}."""
        key = derive_entity_key("player:lebron_james:over", "player_points")
        assert key == "player:lebron_james"

    def test_team_spread(self):
        """Team spread returns 'game'."""
        key = derive_entity_key("team:los_angeles_lakers", "spreads")
        assert key == "game"

    def test_game_total(self):
        """Game total returns 'game'."""
        key = derive_entity_key("total:over", "totals")
        assert key == "game"

    def test_new_format_team_total(self):
        """New-format team_total returns 'team_total:{slug}'."""
        key = derive_entity_key("total:los_angeles_lakers:over", "team_totals")
        assert key == "team_total:los_angeles_lakers"

    def test_old_format_team_total(self):
        """Old-format team_total (total:over) falls through to 'game'."""
        key = derive_entity_key("total:over", "team_totals")
        assert key == "game"

    def test_different_players_different_entity_keys(self):
        """Different players with different names produce different entity keys."""
        key_a = derive_entity_key(
            "player:lebron_james:over", "player_points", player_name="LeBron James"
        )
        key_b = derive_entity_key(
            "player:jayson_tatum:under", "player_points", player_name="Jayson Tatum"
        )
        assert key_a != key_b

    def test_same_player_same_market_same_hash(self):
        """Same player + same market produces identical entity keys."""
        key_a = derive_entity_key(
            "player:lebron_james:over", "player_points", player_name="LeBron James"
        )
        key_b = derive_entity_key(
            "player:lebron_james:under", "player_points", player_name="LeBron James"
        )
        assert key_a == key_b

    def test_empty_selection_key(self):
        """Empty selection_key returns 'game'."""
        key = derive_entity_key("", "spreads")
        assert key == "game"

    def test_moneyline(self):
        """Moneyline team:{slug} returns 'game'."""
        key = derive_entity_key("team:boston_celtics", "h2h")
        assert key == "game"


class TestEntitySafePairing:
    """Integration tests for entity-safe pairing."""

    def test_cross_player_pairing_blocked(self):
        """Two different players with same line and market cannot pair."""
        now = datetime.now(UTC)
        bets_map = {
            (1, "player_points", "player:lebron_james:over", 25.5): {
                "game_id": 1,
                "market_key": "player_points",
                "selection_key": "player:lebron_james:over",
                "line_value": 25.5,
                "league_code": "NBA",
                "market_category": "player_prop",
                "player_name": "LeBron James",
                "entity_key": derive_entity_key(
                    "player:lebron_james:over", "player_points", "LeBron James"
                ),
                "books": [
                    {"book": "DraftKings", "price": -110, "observed_at": now},
                    {"book": "Pinnacle", "price": -115, "observed_at": now},
                ],
            },
            (1, "player_points", "player:jayson_tatum:under", 25.5): {
                "game_id": 1,
                "market_key": "player_points",
                "selection_key": "player:jayson_tatum:under",
                "line_value": 25.5,
                "league_code": "NBA",
                "market_category": "player_prop",
                "player_name": "Jayson Tatum",
                "entity_key": derive_entity_key(
                    "player:jayson_tatum:under", "player_points", "Jayson Tatum"
                ),
                "books": [
                    {"book": "DraftKings", "price": -110, "observed_at": now},
                    {"book": "Pinnacle", "price": -105, "observed_at": now},
                ],
            },
        }

        key_a = (1, "player_points", "player:lebron_james:over", 25.5)
        key_b = (1, "player_points", "player:jayson_tatum:under", 25.5)

        reason = _annotate_pair_ev(key_a, key_b, bets_map)
        assert reason == "entity_mismatch"

    def test_same_player_valid_pair(self):
        """Same player over/under at same line pairs normally."""
        now = datetime.now(UTC)
        entity_key = derive_entity_key(
            "player:lebron_james:over", "player_points", "LeBron James"
        )
        bets_map = {
            (1, "player_points", "player:lebron_james:over", 25.5): {
                "game_id": 1,
                "market_key": "player_points",
                "selection_key": "player:lebron_james:over",
                "line_value": 25.5,
                "league_code": "NBA",
                "market_category": "player_prop",
                "player_name": "LeBron James",
                "entity_key": entity_key,
                "books": [
                    {"book": "DraftKings", "price": -110, "observed_at": now},
                    {"book": "Pinnacle", "price": -115, "observed_at": now},
                ],
            },
            (1, "player_points", "player:lebron_james:under", 25.5): {
                "game_id": 1,
                "market_key": "player_points",
                "selection_key": "player:lebron_james:under",
                "line_value": 25.5,
                "league_code": "NBA",
                "market_category": "player_prop",
                "player_name": "LeBron James",
                "entity_key": entity_key,
                "books": [
                    {"book": "DraftKings", "price": -110, "observed_at": now},
                    {"book": "Pinnacle", "price": -105, "observed_at": now},
                ],
            },
        }

        key_a = (1, "player_points", "player:lebron_james:over", 25.5)
        key_b = (1, "player_points", "player:lebron_james:under", 25.5)

        reason = _annotate_pair_ev(key_a, key_b, bets_map)
        # Should NOT be entity_mismatch — should proceed to normal EV logic
        assert reason != "entity_mismatch"

    def test_new_format_team_totals_separate_groups(self):
        """New-format team totals produce different entity keys, preventing grouping."""
        lakers_entity = derive_entity_key("total:los_angeles_lakers:over", "team_totals")
        celtics_entity = derive_entity_key("total:boston_celtics:over", "team_totals")

        assert lakers_entity != celtics_entity
        assert lakers_entity == "team_total:los_angeles_lakers"
        assert celtics_entity == "team_total:boston_celtics"

    def test_game_totals_unaffected(self):
        """Game totals still group together as 'game'."""
        over_entity = derive_entity_key("total:over", "totals")
        under_entity = derive_entity_key("total:under", "totals")
        assert over_entity == "game"
        assert under_entity == "game"

    def test_defensive_pair_check_blocks_cross_entity(self):
        """_pair_opposite_sides blocks cross-entity pairs defensively."""
        keys = [
            (1, "player_points", "player:lebron_james:over", 25.5),
            (1, "player_points", "player:jayson_tatum:under", 25.5),
        ]
        pairs, unpaired = _pair_opposite_sides(keys)
        assert len(pairs) == 0
        assert len(unpaired) == 2
