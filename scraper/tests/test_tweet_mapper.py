"""Tests for tweet-to-game mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from sports_scraper.social.tweet_mapper import (
    _game_duration_hours,
    _search_dates_for_tweet,
    classify_game_phase,
    get_game_window,
    get_mapping_stats,
    map_tweets_for_team,
    map_unmapped_tweets,
)


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _make_game(**kwargs) -> MagicMock:
    game = MagicMock()
    game.id = kwargs.get("id", 1)
    game.game_date = kwargs.get("game_date", _utc(2025, 6, 15, 0, 0))
    game.end_time = kwargs.get("end_time")
    game.home_team_id = kwargs.get("home_team_id", 100)
    game.away_team_id = kwargs.get("away_team_id", 200)
    # League info for sport-specific durations
    league = kwargs.get("league")
    if league is None:
        league = MagicMock()
        league.code = kwargs.get("league_code", "NBA")
    game.league = league
    return game


def _make_tweet(**kwargs) -> MagicMock:
    tweet = MagicMock()
    tweet.id = kwargs.get("id", 1)
    tweet.team_id = kwargs.get("team_id", 100)
    tweet.posted_at = kwargs.get("posted_at", _utc(2025, 6, 15, 20, 0))
    tweet.mapping_status = kwargs.get("mapping_status", "unmapped")
    tweet.game_id = kwargs.get("game_id")
    tweet.game_phase = kwargs.get("game_phase")
    tweet.updated_at = kwargs.get("updated_at")
    return tweet


# ---------------------------------------------------------------------------
# Sport-specific durations
# ---------------------------------------------------------------------------
class TestGameDurationByLeague:
    def test_nba_duration(self):
        game = _make_game(league_code="NBA")
        assert _game_duration_hours(game) == 3.0

    def test_nhl_duration(self):
        game = _make_game(league_code="NHL")
        assert _game_duration_hours(game) == 3.0

    def test_ncaab_duration(self):
        game = _make_game(league_code="NCAAB")
        assert _game_duration_hours(game) == 2.5

    def test_unknown_league_uses_default(self):
        game = _make_game(league_code="NFL")
        assert _game_duration_hours(game) == 3.0

    def test_no_league_uses_default(self):
        game = _make_game(league=None)
        game.league = None
        assert _game_duration_hours(game) == 3.0


# ---------------------------------------------------------------------------
# get_game_window
# ---------------------------------------------------------------------------
class TestGetGameWindow:
    def test_window_starts_at_5am_et(self):
        """Pregame window starts at 5 AM ET on game_date."""
        # game_date=Jun 15 midnight UTC (EDT offset = -4), 5 AM EDT = 09:00 UTC
        game = _make_game(
            game_date=_utc(2025, 6, 15, 23, 0),  # 7 PM EDT
        )
        start, end = get_game_window(game)
        assert start == _utc(2025, 6, 15, 9, 0)  # 5 AM EDT = 09:00 UTC

    def test_window_starts_at_5am_et_winter(self):
        """During EST (UTC-5), 5 AM ET = 10:00 UTC."""
        game = _make_game(
            game_date=_utc(2026, 2, 6, 1, 10),  # 8:10 PM EST
        )
        start, end = get_game_window(game)
        assert start == _utc(2026, 2, 5, 10, 0)  # 5 AM EST = 10:00 UTC

    def test_postgame_crosses_midnight_et(self):
        """A 10 PM ET tip ends ~1 AM ET next day, postgame until 4 AM ET floor."""
        # 10 PM EST = 03:00 UTC next day
        game = _make_game(
            game_date=_utc(2026, 2, 7, 3, 0),   # 10 PM EST Feb 6
            league_code="NBA",
        )
        start, end = get_game_window(game)
        # NBA duration = 3.0h, so game_end = 06:00 UTC
        # postgame +3h = 09:00 UTC (4:00 AM EST Feb 7)
        # Floor: 4 AM EST Feb 7 = 09:00 UTC Feb 7
        # max(09:00, 09:00) = 09:00 UTC
        assert end == _utc(2026, 2, 7, 9, 0)

    def test_uses_actual_end_time(self):
        game = _make_game(
            game_date=_utc(2025, 6, 15, 19, 0),
            end_time=_utc(2025, 6, 15, 22, 30),
        )
        start, end = get_game_window(game)
        # 3h after actual end = 01:30 UTC Jun 16
        # Floor: 4 AM EDT Jun 16 = 08:00 UTC Jun 16
        # max(01:30, 08:00) = 08:00 UTC
        assert end == _utc(2025, 6, 16, 8, 0)

    def test_ignores_end_time_before_start(self):
        game = _make_game(
            game_date=_utc(2025, 6, 15, 19, 0),
            end_time=_utc(2025, 6, 15, 18, 0),  # before tip
        )
        start, end = get_game_window(game)
        # Falls back to estimated end (tip + 3.0h NBA + 3h postgame) = 01:00 UTC
        # Floor: 4 AM EDT Jun 16 = 08:00 UTC Jun 16
        # max(01:00, 08:00) = 08:00 UTC
        assert end == _utc(2025, 6, 16, 8, 0)

    def test_sport_specific_duration_nhl(self):
        game = _make_game(
            game_date=_utc(2025, 6, 15, 23, 0),
            league_code="NHL",
        )
        start, end = get_game_window(game)
        # NHL: 3.0h duration + 3h postgame = 6.0h after tip = 05:00 UTC Jun 16
        # Floor: 4 AM EDT Jun 16 = 08:00 UTC Jun 16
        # max(05:00, 08:00) = 08:00 UTC
        assert end == _utc(2025, 6, 16, 8, 0)

    def test_sport_specific_duration_ncaab(self):
        game = _make_game(
            game_date=_utc(2025, 6, 15, 23, 0),
            league_code="NCAAB",
        )
        start, end = get_game_window(game)
        # NCAAB: 2.5h duration + 3h postgame = 5.5h after tip = 04:30 UTC Jun 16
        # Floor: 4 AM EDT Jun 16 = 08:00 UTC Jun 16
        # max(04:30, 08:00) = 08:00 UTC
        assert end == _utc(2025, 6, 16, 8, 0)

    def test_naive_datetime_gets_utc(self):
        naive_tip = datetime(2025, 6, 15, 19, 0)  # no tzinfo
        game = _make_game(game_date=naive_tip)
        start, end = get_game_window(game)
        assert start.tzinfo is not None
        assert end.tzinfo is not None

    def test_real_world_pacers_example(self):
        """Pacers game Feb 6 tips 8:10 PM ET (01:10 UTC Feb 7).
        A tweet at 2:50 PM ET (19:50 UTC) should be inside the window.
        """
        game = _make_game(
            game_date=_utc(2026, 2, 7, 1, 10),
        )
        start, end = get_game_window(game)
        assert start == _utc(2026, 2, 6, 10, 0)  # 5 AM EST

        tweet_at = _utc(2026, 2, 6, 19, 50)  # 2:50 PM EST
        assert start <= tweet_at <= end


# ---------------------------------------------------------------------------
# _search_dates_for_tweet
# ---------------------------------------------------------------------------
class TestSearchDatesForTweet:
    def test_afternoon_tweet_searches_today_and_yesterday(self):
        """A tweet at 3 PM ET on Feb 6 should search game_dates Feb 5 and Feb 6.
        game_date is stored as midnight ET → UTC, so bounds are midnight ET → UTC.
        During EST: midnight ET = 05:00 UTC.
        """
        posted_at = _utc(2026, 2, 6, 20, 0)  # 3 PM EST
        search_start, search_end = _search_dates_for_tweet(posted_at)
        assert search_start == _utc(2026, 2, 5, 5, 0)  # midnight EST Feb 5 = 05:00 UTC
        assert search_end == _utc(2026, 2, 6, 5, 0)    # midnight EST Feb 6 = 05:00 UTC

    def test_postgame_tweet_after_midnight_et(self):
        """A tweet at 1 AM ET on Feb 7 (06:00 UTC) should find Feb 6 games.
        ET date is Feb 7, so search Feb 6 and Feb 7.
        """
        posted_at = _utc(2026, 2, 7, 6, 0)  # 1 AM EST Feb 7
        search_start, search_end = _search_dates_for_tweet(posted_at)
        # ET date = Feb 7, search Feb 6 (yesterday) and Feb 7 (today)
        assert search_start == _utc(2026, 2, 6, 5, 0)  # midnight EST Feb 6
        assert search_end == _utc(2026, 2, 7, 5, 0)    # midnight EST Feb 7

    def test_early_morning_utc_tweet(self):
        """A tweet at 3 AM UTC on Feb 7 = 10 PM EST Feb 6.
        Should search Feb 5 and Feb 6 game_dates.
        """
        posted_at = _utc(2026, 2, 7, 3, 0)  # 10 PM EST Feb 6
        search_start, search_end = _search_dates_for_tweet(posted_at)
        assert search_start == _utc(2026, 2, 5, 5, 0)  # midnight EST Feb 5
        assert search_end == _utc(2026, 2, 6, 5, 0)    # midnight EST Feb 6


# ---------------------------------------------------------------------------
# classify_game_phase
# ---------------------------------------------------------------------------
class TestClassifyGamePhase:
    def test_before_tip_is_pregame(self):
        game = _make_game(
            game_date=_utc(2026, 2, 7, 1, 10),  # 8:10 PM EST
        )
        # 3 PM EST = 20:00 UTC
        assert classify_game_phase(_utc(2026, 2, 6, 20, 0), game) == "pregame"

    def test_at_tip_is_in_game(self):
        tip = _utc(2026, 2, 7, 1, 10)
        game = _make_game(game_date=tip)
        assert classify_game_phase(tip, game) == "in_game"

    def test_during_game_is_in_game(self):
        game = _make_game(
            game_date=_utc(2026, 2, 7, 1, 10),
            end_time=_utc(2026, 2, 7, 3, 40),
        )
        assert classify_game_phase(_utc(2026, 2, 7, 2, 0), game) == "in_game"

    def test_after_end_is_postgame(self):
        game = _make_game(
            game_date=_utc(2026, 2, 7, 1, 10),
            end_time=_utc(2026, 2, 7, 3, 40),
        )
        assert classify_game_phase(_utc(2026, 2, 7, 4, 0), game) == "postgame"

    def test_at_end_time_is_in_game(self):
        end = _utc(2026, 2, 7, 3, 40)
        game = _make_game(
            game_date=_utc(2026, 2, 7, 1, 10),
            end_time=end,
        )
        assert classify_game_phase(end, game) == "in_game"

    def test_uses_sport_duration_when_no_end_time(self):
        """NBA game with no end_time: estimated end = tip + 3.0h."""
        game = _make_game(
            game_date=_utc(2026, 2, 7, 1, 10),
            league_code="NBA",
        )
        # 3h after tip → still in_game (within 3.0h)
        assert classify_game_phase(_utc(2026, 2, 7, 4, 0), game) == "in_game"
        # ~3.5h after tip → postgame (past 3.0h)
        assert classify_game_phase(_utc(2026, 2, 7, 4, 40), game) == "postgame"


# ---------------------------------------------------------------------------
# map_unmapped_tweets
# ---------------------------------------------------------------------------
class TestMapUnmappedTweets:
    @patch("sports_scraper.social.tweet_mapper.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_maps_tweet_to_matching_game(self, mock_db, mock_now):
        game = _make_game(
            id=10,
            game_date=_utc(2025, 6, 15, 19, 0),
            home_team_id=100,
        )
        tweet = _make_tweet(
            team_id=100,
            posted_at=_utc(2025, 6, 15, 20, 0),
        )

        session = MagicMock()
        # First call returns tweets, second call returns empty (end loop)
        session.query.return_value.filter.return_value.limit.return_value.all.side_effect = [
            [tweet], []
        ]
        session.query.return_value.filter.return_value.all.return_value = [game]

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_unmapped_tweets(session)

        assert result["mapped"] == 1
        assert result["no_game"] == 0
        assert tweet.mapping_status == "mapped"
        assert tweet.game_id == 10

    @patch("sports_scraper.social.tweet_mapper.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_marks_no_game(self, mock_db, mock_now):
        tweet = _make_tweet(
            team_id=100,
            posted_at=_utc(2025, 6, 15, 20, 0),
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.limit.return_value.all.side_effect = [
            [tweet], []
        ]
        # No matching games
        session.query.return_value.filter.return_value.all.return_value = []

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_unmapped_tweets(session)

        assert result["no_game"] == 1
        assert tweet.mapping_status == "no_game"

    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_empty_batch(self, mock_db):
        session = MagicMock()
        session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_unmapped_tweets(session)

        assert result["total_processed"] == 0
        assert result["mapped"] == 0
        assert result["no_game"] == 0

    @patch("sports_scraper.social.tweet_mapper.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_exception_per_tweet_logged(self, mock_db, mock_now):
        tweet = _make_tweet(team_id=100)
        # Force an exception by making posted_at.tzinfo raise
        tweet.posted_at = MagicMock()
        tweet.posted_at.tzinfo = None
        tweet.posted_at.replace.side_effect = RuntimeError("bad datetime")

        session = MagicMock()
        session.query.return_value.filter.return_value.limit.return_value.all.side_effect = [
            [tweet], []
        ]

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_unmapped_tweets(session)

        assert len(result["errors"]) == 1
        assert result["total_processed"] == 1

    @patch("sports_scraper.social.tweet_mapper.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_returns_summary_stats(self, mock_db, mock_now):
        session = MagicMock()
        session.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_unmapped_tweets(session)

        assert "total_processed" in result
        assert "mapped" in result
        assert "no_game" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# map_tweets_for_team
# ---------------------------------------------------------------------------
class TestMapTweetsForTeam:
    @patch("sports_scraper.social.tweet_mapper.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_maps_for_specific_team(self, mock_db, mock_now):
        game = _make_game(
            id=10,
            game_date=_utc(2025, 6, 15, 19, 0),
        )
        tweet = _make_tweet(
            team_id=100,
            posted_at=_utc(2025, 6, 15, 20, 0),
        )

        session = MagicMock()
        # Unmapped tweets query
        session.query.return_value.filter.return_value.all.return_value = [tweet]
        # Union query for potential games
        session.query.return_value.filter.return_value.union.return_value.all.return_value = [game]

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_tweets_for_team(session, team_id=100)

        assert result["mapped"] == 1
        assert tweet.mapping_status == "mapped"

    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_zero_unmapped_early_return(self, mock_db):
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_tweets_for_team(session, team_id=100)

        assert result["processed"] == 0
        assert result["mapped"] == 0
        assert result["no_game"] == 0

    @patch("sports_scraper.social.tweet_mapper.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_no_matching_game_marks_no_game(self, mock_db, mock_now):
        tweet = _make_tweet(
            team_id=100,
            posted_at=_utc(2025, 6, 15, 20, 0),
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [tweet]
        # No matching games from union query
        session.query.return_value.filter.return_value.union.return_value.all.return_value = []

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = map_tweets_for_team(session, team_id=100)

        assert result["no_game"] == 1
        assert tweet.mapping_status == "no_game"


# ---------------------------------------------------------------------------
# get_mapping_stats
# ---------------------------------------------------------------------------
class TestGetMappingStats:
    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_returns_status_counts(self, mock_db):
        session = MagicMock()
        session.query.return_value.group_by.return_value.all.return_value = [
            ("mapped", 50),
            ("unmapped", 10),
            ("no_game", 5),
        ]

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = get_mapping_stats(session)

        assert result == {"mapped": 50, "unmapped": 10, "no_game": 5}

    @patch("sports_scraper.social.tweet_mapper.db_models", create=True)
    def test_empty_result(self, mock_db):
        session = MagicMock()
        session.query.return_value.group_by.return_value.all.return_value = []

        with patch("sports_scraper.social.tweet_mapper.db_models", mock_db):
            result = get_mapping_stats(session)

        assert result == {}
