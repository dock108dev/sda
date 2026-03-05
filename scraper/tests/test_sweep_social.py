"""Tests for Social Scrape #2: daily sweep postgame collection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch


def _make_game(
    game_id: int = 1,
    status: str = "final",
    social_scrape_1_at=None,
    social_scrape_2_at=None,
    end_time=None,
    home_team_id: int = 10,
    away_team_id: int = 20,
    game_date: datetime | None = None,
):
    """Create a mock game object for testing."""
    game = MagicMock()
    game.id = game_id
    game.status = status
    game.social_scrape_1_at = social_scrape_1_at
    game.social_scrape_2_at = social_scrape_2_at
    game.end_time = end_time
    game.home_team_id = home_team_id
    game.away_team_id = away_team_id
    # Default: midnight ET on Feb 5 = 05:00 UTC (EST convention)
    gd = game_date or datetime(2026, 2, 5, 5, 0, tzinfo=UTC)
    game.game_date = gd
    return game


class TestSocialScrape2:
    """Tests for _run_social_scrape_2 sweep function."""

    @patch("sports_scraper.jobs.sweep_tasks.get_session")
    def test_no_games_returns_early(self, mock_get_session):
        """No eligible games returns zero counts."""
        from sports_scraper.jobs.sweep_tasks import _run_social_scrape_2

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = _run_social_scrape_2()

        assert result["games_found"] == 0
        assert result["games_scraped"] == 0

    @patch("time.sleep")
    @patch("sports_scraper.jobs.sweep_tasks.get_session")
    def test_scrapes_game_date_and_next_day(self, mock_get_session, mock_sleep):
        """Scrape #2 covers game_date and game_date + 1."""
        from sports_scraper.jobs.sweep_tasks import _run_social_scrape_2

        now = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
        game = _make_game(
            social_scrape_1_at=now - timedelta(hours=12),
            end_time=now - timedelta(hours=14),
            game_date=datetime(2026, 2, 5, 5, 0, tzinfo=UTC),  # midnight ET = 05:00 UTC
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [game]
        session.query.return_value.filter.return_value.count.return_value = 0
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "sports_scraper.social.team_collector.TeamTweetCollector"
        ) as MockCollector:
            collector_instance = MockCollector.return_value
            collector_instance.collect_team_tweets.return_value = 2

            with patch("sports_scraper.social.tweet_mapper.map_tweets_for_team"), patch(
                "sports_scraper.utils.datetime_utils.now_utc", return_value=now
            ):
                _run_social_scrape_2()

                # Verify collect_team_tweets was called with game_date and next_day
                calls = collector_instance.collect_team_tweets.call_args_list
                assert len(calls) == 2  # 2 teams

                # Both calls should use (game_date, game_date + 1) range
                from datetime import date

                for c in calls:
                    assert c.kwargs["start_date"] == date(2026, 2, 5)
                    assert c.kwargs["end_date"] == date(2026, 2, 6)

    @patch("sports_scraper.jobs.sweep_tasks.get_session")
    def test_skips_if_scrape_1_not_done(self, mock_get_session):
        """Games without Scrape #1 complete are not processed."""
        from sports_scraper.jobs.sweep_tasks import _run_social_scrape_2

        # The query filter includes social_scrape_1_at.isnot(None),
        # so games without Scrape #1 won't be returned
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = _run_social_scrape_2()
        assert result["games_found"] == 0

    @patch("time.sleep")
    @patch("sports_scraper.jobs.sweep_tasks.get_session")
    def test_sets_scrape_2_at(self, mock_get_session, mock_sleep):
        """After successful scrape, social_scrape_2_at is set."""
        from sports_scraper.jobs.sweep_tasks import _run_social_scrape_2

        now = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
        game = _make_game(
            social_scrape_1_at=now - timedelta(hours=12),
            end_time=now - timedelta(hours=14),
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [game]
        session.query.return_value.filter.return_value.count.return_value = 0
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "sports_scraper.social.team_collector.TeamTweetCollector"
        ) as MockCollector:
            collector_instance = MockCollector.return_value
            collector_instance.collect_team_tweets.return_value = 0

            with patch("sports_scraper.social.tweet_mapper.map_tweets_for_team"), patch(
                "sports_scraper.utils.datetime_utils.now_utc", return_value=now
            ):
                _run_social_scrape_2()

                assert game.social_scrape_2_at is not None
