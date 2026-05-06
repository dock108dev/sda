"""Tests for TeamTweetCollector."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

from sports_scraper.social.exceptions import XCircuitBreakerError
from sports_scraper.social.models import CollectedPost


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _make_post(**kwargs) -> CollectedPost:
    return CollectedPost(
        post_url=kwargs.get("post_url", "https://x.com/team/status/123"),
        external_post_id=kwargs.get("external_post_id", "123"),
        platform="x",
        posted_at=kwargs.get("posted_at", _utc(2025, 6, 15, 20, 0)),
        has_video=kwargs.get("has_video", False),
        text=kwargs.get("text", "Great game!"),
        author_handle=kwargs.get("author_handle", "team_x"),
        video_url=kwargs.get("video_url"),
        image_url=kwargs.get("image_url"),
        media_type=kwargs.get("media_type"),
    )


def _mock_settings() -> MagicMock:
    mock = MagicMock()
    mock.social_config.platform_rate_limit_max_requests = 100
    mock.social_config.platform_rate_limit_window_seconds = 900
    mock.social_config.inter_game_delay_seconds = 15
    mock.social_config.game_batch_size = 5
    mock.social_config.consecutive_known_post_exit = 3
    mock.social_config.max_consecutive_breaker_hits = 3
    mock.social_config.breaker_backoff_seconds = 120
    mock.social_config.pregame_start_hour_et = 5
    return mock


# ---------------------------------------------------------------------------
# TestTeamTweetCollectorInit
# ---------------------------------------------------------------------------
class TestTeamTweetCollectorInit:
    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_with_provided_strategy(self, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        strategy = MagicMock()
        collector = TeamTweetCollector(strategy=strategy)
        assert collector.strategy is strategy
        assert collector.platform == "x"

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=False)
    def test_raises_when_no_playwright(self, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        with pytest.raises(RuntimeError, match="Playwright is required"):
            TeamTweetCollector()


# ---------------------------------------------------------------------------
# TestNormalizePostedAt
# ---------------------------------------------------------------------------
class TestNormalizePostedAt:
    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_naive_datetime(self, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        collector = TeamTweetCollector(strategy=MagicMock())
        naive = datetime(2025, 6, 15, 19, 0)
        result = collector._normalize_posted_at(naive)
        assert result.tzinfo == UTC

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_non_utc_timezone(self, mock_pw):
        from zoneinfo import ZoneInfo

        from sports_scraper.social.team_collector import TeamTweetCollector

        collector = TeamTweetCollector(strategy=MagicMock())
        eastern = datetime(2025, 6, 15, 15, 0, tzinfo=ZoneInfo("America/New_York"))
        result = collector._normalize_posted_at(eastern)
        assert result.tzinfo == UTC
        assert result.hour == 19  # 3 PM ET = 7 PM UTC in summer


# ---------------------------------------------------------------------------
# TestCollectTeamTweets
# ---------------------------------------------------------------------------
class TestCollectTeamTweets:
    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_team_not_found(self, mock_now, mock_extract, mock_fetch, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()
        session.query.return_value.get.return_value = None

        result = collector.collect_team_tweets(
            session, team_id=999, start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
        )
        assert result == 0

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_no_handle(self, mock_now, mock_extract, mock_fetch, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = None
        team.abbreviation = "BOS"

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()
        session.query.return_value.get.return_value = team
        mock_fetch.return_value = {}

        result = collector.collect_team_tweets(
            session, team_id=1, start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
        )
        assert result == 0

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id", return_value="123")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    @patch("sqlalchemy.dialects.postgresql.insert")
    def test_collects_and_saves_new_tweets(self, mock_pg_insert, mock_now, mock_extract, mock_fetch, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = "celtics"
        team.abbreviation = "BOS"

        strategy = MagicMock()
        post = _make_post(external_post_id="456", post_url="https://x.com/celtics/status/456")
        strategy.collect_posts.return_value = [post]

        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()
        session.query.return_value.get.return_value = team
        # Simulate rowcount=1 for the upsert (new row inserted)
        session.execute.return_value.rowcount = 1
        mock_fetch.return_value = {}
        # No existing post in DB
        session.query.return_value.filter.return_value.first.return_value = None

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            result = collector.collect_team_tweets(
                session, team_id=1, start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
            )

        assert result == 1
        session.execute.assert_called_once()
        # One commit happens inside collect_team_tweets — between the read
        # queries and the Playwright fetch — to release AccessShareLocks
        # so a long IO doesn't block migrations or other writers. Writes
        # produced after the fetch are still uncommitted; the caller owns
        # that commit timing.
        assert session.commit.call_count == 1

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id", return_value="123")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_updates_existing_tweet_dedup(self, mock_now, mock_extract, mock_fetch, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = "celtics"
        team.abbreviation = "BOS"

        strategy = MagicMock()
        post = _make_post(external_post_id="123")
        strategy.collect_posts.return_value = [post]

        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()
        session.query.return_value.get.return_value = team
        mock_fetch.return_value = {}

        # Existing post found (dedup)
        existing = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = existing

        with patch("sports_scraper.social.team_collector.db_models", create=True):
            result = collector.collect_team_tweets(
                session, team_id=1, start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
            )

        assert result == 0  # Updated existing, not new
        assert existing.tweet_text == "Great game!"
        # collect_team_tweets commits once mid-method to release read locks
        # before the Playwright fetch (see test_collects_and_saves_new_tweets).
        assert session.commit.call_count == 1

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id", return_value="123")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_circuit_breaker_re_raised(self, mock_now, mock_extract, mock_fetch, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = "celtics"
        team.abbreviation = "BOS"

        strategy = MagicMock()
        strategy.collect_posts.side_effect = XCircuitBreakerError("rate limited", 120)

        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()
        session.query.return_value.get.return_value = team
        mock_fetch.return_value = {}

        with pytest.raises(XCircuitBreakerError):
            collector.collect_team_tweets(
                session, team_id=1, start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
            )

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id", return_value="123")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_window_is_et_based(self, mock_now, mock_extract, mock_fetch, mock_pw):
        """Verify collect window runs from 5 AM ET on start_date to 8 AM ET on end_date+1."""
        from zoneinfo import ZoneInfo

        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = "celtics"
        team.abbreviation = "BOS"

        strategy = MagicMock()
        strategy.collect_posts.return_value = []

        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()
        session.query.return_value.get.return_value = team
        mock_fetch.return_value = {}

        collector.collect_team_tweets(
            session, team_id=1, start_date=date(2026, 2, 5), end_date=date(2026, 2, 5),
        )

        # Verify the window passed to strategy
        strategy.collect_posts.assert_called_once()
        call_kwargs = strategy.collect_posts.call_args[1]
        ws = call_kwargs["window_start"]
        we = call_kwargs["window_end"]

        eastern = ZoneInfo("America/New_York")
        # window_start should be 5 AM ET on Feb 5
        ws_et = ws.astimezone(eastern)
        assert ws_et.hour == 5
        assert ws_et.date() == date(2026, 2, 5)

        # window_end should be 8 AM ET on Feb 6 (end_date + 1)
        we_et = we.astimezone(eastern)
        assert we_et.hour == 8
        assert we_et.date() == date(2026, 2, 6)

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id", return_value="123")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_window_multi_day_range(self, mock_now, mock_extract, mock_fetch, mock_pw):
        """Verify multi-day range: 5 AM ET on start through 8 AM ET on end+1."""
        from zoneinfo import ZoneInfo

        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = "celtics"
        team.abbreviation = "BOS"

        strategy = MagicMock()
        strategy.collect_posts.return_value = []

        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()
        session.query.return_value.get.return_value = team
        mock_fetch.return_value = {}

        collector.collect_team_tweets(
            session, team_id=1, start_date=date(2026, 2, 5), end_date=date(2026, 2, 7),
        )

        call_kwargs = strategy.collect_posts.call_args[1]
        ws = call_kwargs["window_start"]
        we = call_kwargs["window_end"]

        eastern = ZoneInfo("America/New_York")
        ws_et = ws.astimezone(eastern)
        we_et = we.astimezone(eastern)

        # 5 AM ET on Feb 5
        assert ws_et.hour == 5
        assert ws_et.date() == date(2026, 2, 5)

        # 8 AM ET on Feb 8 (end_date Feb 7 + 1 day)
        assert we_et.hour == 8
        assert we_et.date() == date(2026, 2, 8)

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("sports_scraper.social.team_collector.fetch_team_accounts")
    @patch("sports_scraper.social.team_collector.extract_x_post_id", return_value="123")
    @patch("sports_scraper.social.team_collector.now_utc", return_value=_utc(2025, 6, 15, 23, 0))
    def test_generic_error_propagates(self, mock_now, mock_extract, mock_fetch, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        team = MagicMock()
        team.x_handle = "celtics"
        team.abbreviation = "BOS"

        strategy = MagicMock()
        strategy.collect_posts.side_effect = RuntimeError("network error")

        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()
        session.query.return_value.get.return_value = team
        mock_fetch.return_value = {}

        with pytest.raises(RuntimeError, match="network error"):
            collector.collect_team_tweets(
                session, team_id=1, start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
            )


# ---------------------------------------------------------------------------
# TestCollectForDateRange
# ---------------------------------------------------------------------------
class TestCollectForDateRange:
    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_league_not_found(self, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            session.query.return_value.filter.return_value.first.return_value = None
            result = collector.collect_for_date_range(
                session, league_code="FAKE",
                start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
            )

        assert "error" in result

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_no_games_in_range(self, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        league = MagicMock()
        league.id = 1

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            session.query.return_value.filter.return_value.first.return_value = league
            session.query.return_value.filter.return_value.all.return_value = []

            result = collector.collect_for_date_range(
                session, league_code="NBA",
                start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
            )

        assert result["teams_processed"] == 0
        assert result["total_new_tweets"] == 0

    @patch("time.sleep")
    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_collects_for_all_unique_teams(self, mock_pw, mock_sleep):
        from sports_scraper.social.team_collector import TeamTweetCollector

        league = MagicMock()
        league.id = 1

        game1 = MagicMock()
        game1.home_team_id = 100
        game1.away_team_id = 200
        game2 = MagicMock()
        game2.home_team_id = 100  # duplicate
        game2.away_team_id = 300

        strategy = MagicMock()
        collector = TeamTweetCollector(strategy=strategy)
        session = MagicMock()

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            session.query.return_value.filter.return_value.first.return_value = league
            session.query.return_value.filter.return_value.all.return_value = [game1, game2]

            with patch.object(collector, "collect_team_tweets", return_value=2) as mock_collect:
                result = collector.collect_for_date_range(
                    session, league_code="NBA",
                    start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
                )

        assert result["teams_processed"] == 3  # 100, 200, 300
        assert result["total_new_tweets"] == 6  # 2 per team * 3

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("time.sleep")
    def test_circuit_breaker_3_strike_abort(self, mock_sleep, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        league = MagicMock()
        league.id = 1

        game = MagicMock()
        game.home_team_id = 100
        game.away_team_id = 200

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            session.query.return_value.filter.return_value.first.return_value = league
            session.query.return_value.filter.return_value.all.return_value = [game]

            with patch.object(
                collector, "collect_team_tweets",
                side_effect=XCircuitBreakerError("rate limited", 120),
            ):
                result = collector.collect_for_date_range(
                    session, league_code="NBA",
                    start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
                )

        assert result["teams_processed"] == 0
        assert result["errors"] is not None

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    @patch("time.sleep")
    def test_breaker_resets_on_success(self, mock_sleep, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        league = MagicMock()
        league.id = 1

        game = MagicMock()
        game.home_team_id = 100
        game.away_team_id = 200

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()

        call_count = 0

        def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise XCircuitBreakerError("rate limited", 120)
            return 3

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            session.query.return_value.filter.return_value.first.return_value = league
            session.query.return_value.filter.return_value.all.return_value = [game]

            with patch.object(collector, "collect_team_tweets", side_effect=side_effect):
                result = collector.collect_for_date_range(
                    session, league_code="NBA",
                    start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
                )

        assert result["teams_processed"] == 1
        assert result["total_new_tweets"] == 3

    @patch("sports_scraper.social.team_collector.settings", _mock_settings())
    @patch("sports_scraper.social.team_collector.playwright_available", return_value=True)
    def test_generic_exception_per_team(self, mock_pw):
        from sports_scraper.social.team_collector import TeamTweetCollector

        league = MagicMock()
        league.id = 1

        game = MagicMock()
        game.home_team_id = 100
        game.away_team_id = 200

        collector = TeamTweetCollector(strategy=MagicMock())
        session = MagicMock()

        with patch("sports_scraper.social.team_collector.db_models", create=True) as mock_db:
            session.query.return_value.filter.return_value.first.return_value = league
            session.query.return_value.filter.return_value.all.return_value = [game]

            with patch.object(
                collector, "collect_team_tweets",
                side_effect=RuntimeError("oops"),
            ):
                result = collector.collect_for_date_range(
                    session, league_code="NBA",
                    start_date=date(2025, 6, 15), end_date=date(2025, 6, 15),
                )

        assert result["errors"] is not None
        assert len(result["errors"]) == 2  # Both teams errored
