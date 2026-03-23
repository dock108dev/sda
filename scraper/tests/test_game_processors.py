"""Tests for game_processors and all league-specific processor modules."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_ROOT = REPO_ROOT / "scraper"
if str(SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test_db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest

from sports_scraper.services.game_processors import (
    GameProcessResult,
    process_game_boxscore,
    process_game_pbp,
)
from sports_scraper.services.game_processors_mlb import (
    check_game_status_mlb,
    process_game_boxscore_mlb,
    process_game_pbp_mlb,
)
from sports_scraper.services.game_processors_nba import (
    check_game_status_nba,
    process_game_boxscore_nba,
    process_game_pbp_nba,
)
from sports_scraper.services.game_processors_ncaab import (
    process_game_boxscore_ncaab,
    process_game_boxscores_ncaab_batch,
    process_game_pbp_ncaab,
)
from sports_scraper.services.game_processors_nfl import (
    check_game_status_nfl,
    process_game_boxscore_nfl,
    process_game_pbp_nfl,
)
from sports_scraper.services.game_processors_nhl import (
    check_game_status_nhl,
    process_game_boxscore_nhl,
    process_game_pbp_nhl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game(external_ids=None, status="pregame", game_date=None, **kwargs):
    """Create a mock SportsGame object."""
    game = MagicMock()
    game.id = kwargs.get("id", 1)
    game.external_ids = external_ids or {}
    game.status = status
    game.game_date = game_date or datetime(2025, 3, 1, tzinfo=UTC)
    game.home_score = kwargs.get("home_score", 0)
    game.away_score = kwargs.get("away_score", 0)
    game.end_time = kwargs.get("end_time", None)
    game.last_pbp_at = None
    game.last_boxscore_at = None
    game.updated_at = None
    game.home_team_id = kwargs.get("home_team_id", 10)
    game.away_team_id = kwargs.get("away_team_id", 20)
    return game


def _mock_pbp_payload(plays=None):
    """Create a mock PBP payload."""
    payload = MagicMock()
    payload.plays = plays if plays is not None else []
    return payload


def _mock_boxscore(team_boxscores=None, player_boxscores=None):
    """Create a mock boxscore response."""
    box = MagicMock()
    box.team_boxscores = team_boxscores if team_boxscores is not None else []
    box.player_boxscores = player_boxscores if player_boxscores is not None else []
    return box


# ===========================================================================
# GameProcessResult dataclass
# ===========================================================================

class TestGameProcessResult:
    def test_defaults(self):
        r = GameProcessResult()
        assert r.api_calls == 0
        assert r.events_inserted == 0
        assert r.boxscore_updated is False
        assert r.transition is None
        assert r.error is None

    def test_custom_values(self):
        r = GameProcessResult(api_calls=2, events_inserted=10, boxscore_updated=True)
        assert r.api_calls == 2
        assert r.events_inserted == 10
        assert r.boxscore_updated is True


# ===========================================================================
# Dispatchers (game_processors.py lines 71-98)
# ===========================================================================

class TestProcessGamePbpDispatcher:
    @patch("sports_scraper.services.game_processors.process_game_pbp_nba")
    def test_dispatches_nba(self, mock_fn):
        mock_fn.return_value = GameProcessResult(api_calls=1)
        session = MagicMock()
        game = _make_game()
        result = process_game_pbp(session, game, "NBA")
        mock_fn.assert_called_once_with(session, game)
        assert result.api_calls == 1

    @patch("sports_scraper.services.game_processors.process_game_pbp_nhl")
    def test_dispatches_nhl(self, mock_fn):
        mock_fn.return_value = GameProcessResult(api_calls=1)
        result = process_game_pbp(MagicMock(), _make_game(), "NHL")
        mock_fn.assert_called_once()

    @patch("sports_scraper.services.game_processors.process_game_pbp_mlb")
    def test_dispatches_mlb(self, mock_fn):
        mock_fn.return_value = GameProcessResult(api_calls=1)
        result = process_game_pbp(MagicMock(), _make_game(), "MLB")
        mock_fn.assert_called_once()

    @patch("sports_scraper.services.game_processors.process_game_pbp_ncaab")
    def test_dispatches_ncaab(self, mock_fn):
        mock_fn.return_value = GameProcessResult(api_calls=1)
        result = process_game_pbp(MagicMock(), _make_game(), "NCAAB")
        mock_fn.assert_called_once()

    @patch("sports_scraper.services.game_processors.process_game_pbp_nfl")
    def test_dispatches_nfl(self, mock_fn):
        mock_fn.return_value = GameProcessResult(api_calls=1)
        result = process_game_pbp(MagicMock(), _make_game(), "NFL")
        mock_fn.assert_called_once()

    def test_unknown_league_returns_empty(self):
        result = process_game_pbp(MagicMock(), _make_game(), "WNBA")
        assert result.api_calls == 0


class TestProcessGameBoxscoreDispatcher:
    @patch("sports_scraper.services.game_processors.process_game_boxscore_nba")
    def test_dispatches_nba(self, mock_fn):
        mock_fn.return_value = GameProcessResult(boxscore_updated=True)
        result = process_game_boxscore(MagicMock(), _make_game(), "NBA")
        mock_fn.assert_called_once()
        assert result.boxscore_updated is True

    @patch("sports_scraper.services.game_processors.process_game_boxscore_nhl")
    def test_dispatches_nhl(self, mock_fn):
        mock_fn.return_value = GameProcessResult(boxscore_updated=True)
        result = process_game_boxscore(MagicMock(), _make_game(), "NHL")
        mock_fn.assert_called_once()

    @patch("sports_scraper.services.game_processors.process_game_boxscore_mlb")
    def test_dispatches_mlb(self, mock_fn):
        mock_fn.return_value = GameProcessResult(boxscore_updated=True)
        result = process_game_boxscore(MagicMock(), _make_game(), "MLB")
        mock_fn.assert_called_once()

    @patch("sports_scraper.services.game_processors.process_game_boxscore_ncaab")
    def test_dispatches_ncaab(self, mock_fn):
        mock_fn.return_value = GameProcessResult(boxscore_updated=True)
        result = process_game_boxscore(MagicMock(), _make_game(), "NCAAB")
        mock_fn.assert_called_once()

    @patch("sports_scraper.services.game_processors.process_game_boxscore_nfl")
    def test_dispatches_nfl(self, mock_fn):
        mock_fn.return_value = GameProcessResult(boxscore_updated=True)
        result = process_game_boxscore(MagicMock(), _make_game(), "NFL")
        mock_fn.assert_called_once()

    def test_unknown_league_returns_empty(self):
        result = process_game_boxscore(MagicMock(), _make_game(), "WNBA")
        assert result.api_calls == 0
        assert result.boxscore_updated is False


# ===========================================================================
# NBA (game_processors_nba.py)
# ===========================================================================

class TestCheckGameStatusNba:
    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_status_transition(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 3, 1)
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_resolve.return_value = "live"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = "0022400100"
        sg.status = "live"
        sg.home_score = 55
        sg.away_score = 48
        client.fetch_scoreboard.return_value = [sg]

        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
            status="pregame",
        )
        result = check_game_status_nba(MagicMock(), game, client=client)

        assert result.api_calls == 1
        assert result.transition is not None
        assert result.transition["from"] == "pregame"
        assert result.transition["to"] == "live"
        assert game.home_score == 55
        assert game.away_score == 48

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_transition_to_final_sets_end_time(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 3, 1)
        now_val = datetime(2025, 3, 1, 23, 0, 0, tzinfo=UTC)
        mock_now.return_value = now_val
        mock_resolve.return_value = "final"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = "0022400100"
        sg.status = "final"
        sg.home_score = 110
        sg.away_score = 105
        client.fetch_scoreboard.return_value = [sg]

        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
            status="live",
            end_time=None,
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.final.value = "final"
            result = check_game_status_nba(MagicMock(), game, client=client)

        assert game.end_time == now_val

    def test_missing_nba_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = check_game_status_nba(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_missing_game_date_returns_empty(self, mock_to_et):
        mock_to_et.return_value = None
        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
            game_date=None,
        )
        result = check_game_status_nba(MagicMock(), game, client=MagicMock())
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_no_matching_game_in_scoreboard(self, mock_to_et, mock_resolve):
        mock_to_et.return_value = date(2025, 3, 1)

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = "other_id"
        client.fetch_scoreboard.return_value = [sg]

        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
        )
        result = check_game_status_nba(MagicMock(), game, client=client)
        assert result.api_calls == 1
        assert result.transition is None

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_no_status_change(self, mock_to_et, mock_resolve):
        mock_to_et.return_value = date(2025, 3, 1)
        mock_resolve.return_value = "live"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = "0022400100"
        sg.status = "live"
        sg.home_score = None
        sg.away_score = None
        client.fetch_scoreboard.return_value = [sg]

        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
            status="live",
        )
        result = check_game_status_nba(MagicMock(), game, client=client)
        assert result.transition is None


class TestProcessGamePbpNba:
    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_inserts_plays(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 5

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1", "p2"])

        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
            status="live",
        )
        session = MagicMock()
        result = process_game_pbp_nba(session, game, client=client)

        assert result.api_calls == 1
        assert result.events_inserted == 5
        mock_upsert.assert_called_once_with(session, game.id, ["p1", "p2"], source="nba_api")

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_infers_live_from_pregame(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 3

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(
            external_ids={"nba_game_id": "0022400100"},
            status="pregame",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.pregame.value = "pregame"
            mock_db.GameStatus.live.value = "live"
            result = process_game_pbp_nba(MagicMock(), game, client=client)

        assert result.transition is not None
        assert result.transition["to"] == "live"
        assert game.status == "live"

    def test_missing_nba_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_pbp_nba(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_no_plays_returns_zero_events(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 1, tzinfo=UTC)
        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=[])

        game = _make_game(external_ids={"nba_game_id": "0022400100"})
        result = process_game_pbp_nba(MagicMock(), game, client=client)
        assert result.api_calls == 1
        assert result.events_inserted == 0


class TestProcessGameBoxscoreNba:
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_upserts_boxscores(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        client = MagicMock()
        tb = [MagicMock(), MagicMock()]
        pb = [MagicMock(), MagicMock(), MagicMock()]
        client.fetch_boxscore.return_value = _mock_boxscore(
            team_boxscores=tb, player_boxscores=pb,
        )

        game = _make_game(external_ids={"nba_game_id": "0022400100"})
        session = MagicMock()
        result = process_game_boxscore_nba(session, game, client=client)

        assert result.api_calls == 1
        assert result.boxscore_updated is True
        mock_team.assert_called_once_with(session, game.id, tb, source="nba_api")
        mock_player.assert_called_once_with(session, game.id, pb, source="nba_api")

    def test_missing_nba_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_boxscore_nba(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_null_boxscore_not_updated(self, mock_now):
        mock_now.return_value = datetime(2025, 3, 1, tzinfo=UTC)
        client = MagicMock()
        client.fetch_boxscore.return_value = None

        game = _make_game(external_ids={"nba_game_id": "0022400100"})
        result = process_game_boxscore_nba(MagicMock(), game, client=client)
        assert result.api_calls == 1
        assert result.boxscore_updated is False

    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_empty_team_and_player_lists(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 1, tzinfo=UTC)

        client = MagicMock()
        client.fetch_boxscore.return_value = _mock_boxscore(
            team_boxscores=[], player_boxscores=[],
        )

        game = _make_game(external_ids={"nba_game_id": "0022400100"})
        result = process_game_boxscore_nba(MagicMock(), game, client=client)
        assert result.boxscore_updated is True
        mock_team.assert_not_called()
        mock_player.assert_not_called()


# ===========================================================================
# NHL (game_processors_nhl.py)
# ===========================================================================

class TestCheckGameStatusNhl:
    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_status_transition(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 3, 1)
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_resolve.return_value = "live"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = 2024020100
        sg.status = "live"
        sg.home_score = 3
        sg.away_score = 2
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"nhl_game_pk": "2024020100"},
            status="pregame",
        )
        result = check_game_status_nhl(MagicMock(), game, client=client)

        assert result.api_calls == 1
        assert result.transition is not None
        assert result.transition["to"] == "live"
        assert game.home_score == 3

    def test_missing_nhl_game_pk_returns_empty(self):
        game = _make_game(external_ids={})
        result = check_game_status_nhl(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_nhl_game_pk_returns_empty(self):
        game = _make_game(external_ids={"nhl_game_pk": "not_a_number"})
        result = check_game_status_nhl(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_missing_game_date_returns_empty(self, mock_to_et):
        mock_to_et.return_value = None
        game = _make_game(
            external_ids={"nhl_game_pk": "2024020100"},
            game_date=None,
        )
        result = check_game_status_nhl(MagicMock(), game, client=MagicMock())
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_transition_to_final_sets_end_time(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 3, 1)
        now_val = datetime(2025, 3, 1, 23, 0, 0, tzinfo=UTC)
        mock_now.return_value = now_val
        mock_resolve.return_value = "final"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = 2024020100
        sg.status = "final"
        sg.home_score = 4
        sg.away_score = 2
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"nhl_game_pk": "2024020100"},
            status="live",
            end_time=None,
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.final.value = "final"
            result = check_game_status_nhl(MagicMock(), game, client=client)

        assert game.end_time == now_val


class TestProcessGamePbpNhl:
    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_inserts_plays(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 8

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(external_ids={"nhl_game_pk": "2024020100"}, status="live")
        session = MagicMock()
        result = process_game_pbp_nhl(session, game, client=client)

        assert result.api_calls == 1
        assert result.events_inserted == 8
        mock_upsert.assert_called_once()

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_infers_live_from_pregame(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 3

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(external_ids={"nhl_game_pk": "2024020100"}, status="pregame")

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.pregame.value = "pregame"
            mock_db.GameStatus.live.value = "live"
            result = process_game_pbp_nhl(MagicMock(), game, client=client)

        assert result.transition is not None
        assert result.transition["to"] == "live"

    def test_missing_nhl_game_pk_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_pbp_nhl(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_nhl_game_pk_returns_empty(self):
        game = _make_game(external_ids={"nhl_game_pk": "bad"})
        result = process_game_pbp_nhl(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_no_plays_returns_zero_events(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 1, tzinfo=UTC)
        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=[])
        game = _make_game(external_ids={"nhl_game_pk": "2024020100"})
        result = process_game_pbp_nhl(MagicMock(), game, client=client)
        assert result.api_calls == 1
        assert result.events_inserted == 0


class TestProcessGameBoxscoreNhl:
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_upserts_boxscores(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        client = MagicMock()
        tb = [MagicMock()]
        pb = [MagicMock()]
        client.fetch_boxscore.return_value = _mock_boxscore(
            team_boxscores=tb, player_boxscores=pb,
        )

        game = _make_game(external_ids={"nhl_game_pk": "2024020100"})
        session = MagicMock()
        result = process_game_boxscore_nhl(session, game, client=client)

        assert result.api_calls == 1
        assert result.boxscore_updated is True
        mock_team.assert_called_once_with(session, game.id, tb, source="nhl_api")
        mock_player.assert_called_once_with(session, game.id, pb, source="nhl_api")

    def test_missing_nhl_game_pk_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_boxscore_nhl(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_nhl_game_pk_returns_empty(self):
        game = _make_game(external_ids={"nhl_game_pk": "bad"})
        result = process_game_boxscore_nhl(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_null_boxscore_not_updated(self, mock_now):
        mock_now.return_value = datetime(2025, 3, 1, tzinfo=UTC)
        client = MagicMock()
        client.fetch_boxscore.return_value = None
        game = _make_game(external_ids={"nhl_game_pk": "2024020100"})
        result = process_game_boxscore_nhl(MagicMock(), game, client=client)
        assert result.boxscore_updated is False


# ===========================================================================
# MLB (game_processors_mlb.py)
# ===========================================================================

class TestCheckGameStatusMlb:
    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_status_transition(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 6, 15)
        mock_now.return_value = datetime(2025, 6, 15, 20, 0, 0, tzinfo=UTC)
        mock_resolve.return_value = "live"

        client = MagicMock()
        sg = MagicMock()
        sg.game_pk = 717001
        sg.status = "live"
        sg.home_score = 5
        sg.away_score = 3
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"mlb_game_pk": "717001"},
            status="pregame",
        )
        result = check_game_status_mlb(MagicMock(), game, client=client)

        assert result.api_calls == 1
        assert result.transition is not None
        assert result.transition["to"] == "live"
        assert game.home_score == 5

    def test_missing_mlb_game_pk_returns_empty(self):
        game = _make_game(external_ids={})
        result = check_game_status_mlb(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_mlb_game_pk_returns_empty(self):
        game = _make_game(external_ids={"mlb_game_pk": "bad"})
        result = check_game_status_mlb(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_missing_game_date_returns_empty(self, mock_to_et):
        mock_to_et.return_value = None
        game = _make_game(
            external_ids={"mlb_game_pk": "717001"},
            game_date=None,
        )
        result = check_game_status_mlb(MagicMock(), game, client=MagicMock())
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_transition_to_final_sets_end_time(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 6, 15)
        now_val = datetime(2025, 6, 15, 23, 0, 0, tzinfo=UTC)
        mock_now.return_value = now_val
        mock_resolve.return_value = "final"

        client = MagicMock()
        sg = MagicMock()
        sg.game_pk = 717001
        sg.status = "final"
        sg.home_score = 7
        sg.away_score = 4
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"mlb_game_pk": "717001"},
            status="live",
            end_time=None,
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.final.value = "final"
            result = check_game_status_mlb(MagicMock(), game, client=client)

        assert game.end_time == now_val


class TestProcessGamePbpMlb:
    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_inserts_plays(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 6, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 12

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1", "p2"])

        game = _make_game(external_ids={"mlb_game_pk": "717001"}, status="live")
        session = MagicMock()
        result = process_game_pbp_mlb(session, game, client=client)

        assert result.api_calls == 1
        assert result.events_inserted == 12
        client.fetch_play_by_play.assert_called_once_with(717001, game_status="live")

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_infers_live_from_pregame(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 6, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 3

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(external_ids={"mlb_game_pk": "717001"}, status="pregame")

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.pregame.value = "pregame"
            mock_db.GameStatus.live.value = "live"
            result = process_game_pbp_mlb(MagicMock(), game, client=client)

        assert result.transition is not None
        assert result.transition["to"] == "live"

    def test_missing_mlb_game_pk_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_pbp_mlb(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_mlb_game_pk_returns_empty(self):
        game = _make_game(external_ids={"mlb_game_pk": "bad"})
        result = process_game_pbp_mlb(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_no_plays_returns_zero_events(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 6, 15, tzinfo=UTC)
        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=[])
        game = _make_game(external_ids={"mlb_game_pk": "717001"})
        result = process_game_pbp_mlb(MagicMock(), game, client=client)
        assert result.api_calls == 1
        assert result.events_inserted == 0


class TestProcessGameBoxscoreMlb:
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_upserts_boxscores(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 6, 15, 20, 0, 0, tzinfo=UTC)

        client = MagicMock()
        tb = [MagicMock()]
        pb = [MagicMock()]
        client.fetch_boxscore.return_value = _mock_boxscore(
            team_boxscores=tb, player_boxscores=pb,
        )

        game = _make_game(external_ids={"mlb_game_pk": "717001"}, status="final")
        session = MagicMock()
        result = process_game_boxscore_mlb(session, game, client=client)

        assert result.api_calls == 1
        assert result.boxscore_updated is True
        mock_team.assert_called_once_with(session, game.id, tb, source="mlb_api")
        client.fetch_boxscore.assert_called_once_with(717001, game_status="final")

    def test_missing_mlb_game_pk_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_boxscore_mlb(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_mlb_game_pk_returns_empty(self):
        game = _make_game(external_ids={"mlb_game_pk": "bad"})
        result = process_game_boxscore_mlb(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_null_boxscore_not_updated(self, mock_now):
        mock_now.return_value = datetime(2025, 6, 15, tzinfo=UTC)
        client = MagicMock()
        client.fetch_boxscore.return_value = None
        game = _make_game(external_ids={"mlb_game_pk": "717001"})
        result = process_game_boxscore_mlb(MagicMock(), game, client=client)
        assert result.boxscore_updated is False


# ===========================================================================
# NCAAB (game_processors_ncaab.py)
# ===========================================================================

class TestProcessGamePbpNcaab:
    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_cbb_api_inserts_plays(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 10

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(
            external_ids={"cbb_game_id": "12345"},
            status="live",
        )
        session = MagicMock()
        result = process_game_pbp_ncaab(session, game, client=client)

        assert result.api_calls == 1
        assert result.events_inserted == 10
        mock_upsert.assert_called_once_with(session, game.id, ["p1"], source="cbb_api")

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_cbb_api_infers_live_from_pregame(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 5

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(
            external_ids={"cbb_game_id": "12345"},
            status="pregame",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.pregame.value = "pregame"
            mock_db.GameStatus.live.value = "live"
            result = process_game_pbp_ncaab(MagicMock(), game, client=client)

        assert result.transition is not None
        assert result.transition["to"] == "live"

    def test_no_external_ids_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_pbp_ncaab(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_cbb_game_id_falls_through(self):
        """Invalid cbb_game_id should skip CBB and try NCAA fallback."""
        client = MagicMock()
        game = _make_game(external_ids={"cbb_game_id": "not_a_number"})
        result = process_game_pbp_ncaab(MagicMock(), game, client=client)
        assert result.events_inserted == 0

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_ncaa_fallback_when_cbb_has_no_plays(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 7

        client = MagicMock()
        # CBB returns no plays
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=[])
        # NCAA fallback returns plays
        client.fetch_ncaa_play_by_play.return_value = _mock_pbp_payload(plays=["np1"])

        session = MagicMock()
        home_team = MagicMock()
        home_team.abbreviation = "DUKE"
        away_team = MagicMock()
        away_team.abbreviation = "UNC"
        session.query.return_value.get.side_effect = [home_team, away_team]

        game = _make_game(
            external_ids={"cbb_game_id": "12345", "ncaa_game_id": "NCAA123"},
            status="live",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            mock_db.GameStatus.pregame.value = "pregame"
            result = process_game_pbp_ncaab(session, game, client=client)

        assert result.api_calls == 2
        assert result.events_inserted == 7
        mock_upsert.assert_called_with(session, game.id, ["np1"], source="ncaa_api")

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_ncaa_only_when_no_cbb_id(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 4

        client = MagicMock()
        client.fetch_ncaa_play_by_play.return_value = _mock_pbp_payload(plays=["np1"])

        session = MagicMock()
        home_team = MagicMock()
        home_team.abbreviation = "KU"
        away_team = MagicMock()
        away_team.abbreviation = "KSU"
        session.query.return_value.get.side_effect = [home_team, away_team]

        game = _make_game(
            external_ids={"ncaa_game_id": "NCAA456"},
            status="live",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            mock_db.GameStatus.pregame.value = "pregame"
            result = process_game_pbp_ncaab(session, game, client=client)

        assert result.api_calls == 1
        assert result.events_inserted == 4

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_ncaa_fallback_infers_live_from_pregame(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 2

        client = MagicMock()
        client.fetch_ncaa_play_by_play.return_value = _mock_pbp_payload(plays=["np1"])

        session = MagicMock()
        session.query.return_value.get.return_value = MagicMock(abbreviation="X")

        game = _make_game(
            external_ids={"ncaa_game_id": "NCAA789"},
            status="pregame",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.pregame.value = "pregame"
            mock_db.GameStatus.live.value = "live"
            mock_db.SportsTeam = MagicMock()
            result = process_game_pbp_ncaab(session, game, client=client)

        assert result.transition is not None
        assert result.transition["to"] == "live"

    def test_ncaa_fallback_missing_teams(self):
        """NCAA fallback works even when team lookups return None."""
        client = MagicMock()
        client.fetch_ncaa_play_by_play.return_value = _mock_pbp_payload(plays=[])

        session = MagicMock()
        session.query.return_value.get.return_value = None

        game = _make_game(
            external_ids={"ncaa_game_id": "NCAA456"},
            status="live",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            mock_db.GameStatus.pregame.value = "pregame"
            result = process_game_pbp_ncaab(session, game, client=client)

        assert result.api_calls == 1


class TestProcessGameBoxscoreNcaab:
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_upserts_boxscores(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)

        client = MagicMock()
        tb = [MagicMock()]
        pb = [MagicMock()]
        client.fetch_ncaa_boxscore.return_value = _mock_boxscore(
            team_boxscores=tb, player_boxscores=pb,
        )

        session = MagicMock()
        home_team = MagicMock()
        home_team.name = "Duke"
        away_team = MagicMock()
        away_team.name = "UNC"
        session.query.return_value.get.side_effect = [home_team, away_team]

        game = _make_game(
            external_ids={"ncaa_game_id": "NCAA123"},
            status="final",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            result = process_game_boxscore_ncaab(session, game, client=client)

        assert result.api_calls == 1
        assert result.boxscore_updated is True
        mock_team.assert_called_once()
        mock_player.assert_called_once()

    def test_missing_ncaa_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_boxscore_ncaab(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_null_boxscore_not_updated(self, mock_now):
        mock_now.return_value = datetime(2025, 3, 15, tzinfo=UTC)
        client = MagicMock()
        client.fetch_ncaa_boxscore.return_value = None

        session = MagicMock()
        session.query.return_value.get.return_value = MagicMock(name="Team")

        game = _make_game(external_ids={"ncaa_game_id": "NCAA123"})

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            result = process_game_boxscore_ncaab(session, game, client=client)

        assert result.boxscore_updated is False

    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_missing_teams_uses_unknown(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)

        client = MagicMock()
        client.fetch_ncaa_boxscore.return_value = _mock_boxscore(
            team_boxscores=[MagicMock()], player_boxscores=[],
        )

        session = MagicMock()
        session.query.return_value.get.return_value = None

        game = _make_game(external_ids={"ncaa_game_id": "NCAA123"})

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            result = process_game_boxscore_ncaab(session, game, client=client)

        assert result.boxscore_updated is True
        call_kwargs = client.fetch_ncaa_boxscore.call_args
        assert call_kwargs[1]["home_team_name"] == "Unknown"
        assert call_kwargs[1]["away_team_name"] == "Unknown"


class TestProcessGameBoxscoresNcaabBatch:
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    @patch("sports_scraper.utils.date_utils.season_ending_year")
    def test_batch_processes_games(self, mock_season, mock_to_et, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_to_et.return_value = date(2025, 3, 15)
        mock_season.return_value = 2025

        client = MagicMock()
        box1 = _mock_boxscore(team_boxscores=[MagicMock()], player_boxscores=[MagicMock()])
        client.fetch_boxscores_batch.return_value = {100: box1}

        session = MagicMock()
        game1 = _make_game(
            id=1,
            external_ids={"cbb_game_id": "100"},
        )
        game2 = _make_game(
            id=2,
            external_ids={},
        )

        results = process_game_boxscores_ncaab_batch(
            session, [game1, game2],
            client=client,
            team_names_by_game_id={1: ("Duke", "UNC"), 2: ("UK", "UL")},
        )

        assert len(results) == 2
        assert results[0].boxscore_updated is True
        assert results[0].api_calls == 2
        assert results[1].boxscore_updated is False

    def test_empty_games_list(self):
        results = process_game_boxscores_ncaab_batch(MagicMock(), [])
        assert results == []

    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_no_cbb_game_ids(self, mock_to_et):
        """All games missing cbb_game_id returns empty results."""
        game = _make_game(external_ids={})
        results = process_game_boxscores_ncaab_batch(
            MagicMock(), [game],
            team_names_by_game_id={1: ("A", "B")},
        )
        assert len(results) == 1
        assert results[0].boxscore_updated is False

    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    @patch("sports_scraper.utils.date_utils.season_ending_year")
    def test_batch_builds_team_names_from_db(self, mock_season, mock_to_et, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 3, 15, 20, 0, 0, tzinfo=UTC)
        mock_to_et.return_value = date(2025, 3, 15)
        mock_season.return_value = 2025

        client = MagicMock()
        client.fetch_boxscores_batch.return_value = {}

        session = MagicMock()
        home_team = MagicMock()
        home_team.name = "Duke"
        away_team = MagicMock()
        away_team.name = "UNC"
        session.query.return_value.get.side_effect = [home_team, away_team]

        game = _make_game(
            external_ids={"cbb_game_id": "100"},
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.SportsTeam = MagicMock()
            results = process_game_boxscores_ncaab_batch(
                session, [game],
                client=client,
                team_names_by_game_id=None,
            )

        assert len(results) == 1

    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_invalid_cbb_game_id_skipped(self, mock_to_et):
        """Invalid (non-numeric) cbb_game_id games are skipped."""
        game = _make_game(external_ids={"cbb_game_id": "bad"})
        results = process_game_boxscores_ncaab_batch(
            MagicMock(), [game],
            team_names_by_game_id={1: ("A", "B")},
        )
        assert len(results) == 1
        assert results[0].boxscore_updated is False


# ===========================================================================
# NFL (game_processors_nfl.py)
# ===========================================================================

class TestCheckGameStatusNfl:
    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_status_transition(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 9, 7)
        mock_now.return_value = datetime(2025, 9, 7, 20, 0, 0, tzinfo=UTC)
        mock_resolve.return_value = "live"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = 401547000
        sg.status = "live"
        sg.home_score = 14
        sg.away_score = 7
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
            status="pregame",
        )
        result = check_game_status_nfl(MagicMock(), game, client=client)

        assert result.api_calls == 1
        assert result.transition is not None
        assert result.transition["to"] == "live"
        assert game.home_score == 14

    def test_missing_espn_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = check_game_status_nfl(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_espn_game_id_returns_empty(self):
        game = _make_game(external_ids={"espn_game_id": "bad"})
        result = check_game_status_nfl(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_missing_game_date_returns_empty(self, mock_to_et):
        mock_to_et.return_value = None
        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
            game_date=None,
        )
        result = check_game_status_nfl(MagicMock(), game, client=MagicMock())
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_transition_to_final_sets_end_time(self, mock_to_et, mock_now, mock_resolve):
        mock_to_et.return_value = date(2025, 9, 7)
        now_val = datetime(2025, 9, 7, 23, 30, 0, tzinfo=UTC)
        mock_now.return_value = now_val
        mock_resolve.return_value = "final"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = 401547000
        sg.status = "final"
        sg.home_score = 24
        sg.away_score = 21
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
            status="live",
            end_time=None,
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.final.value = "final"
            result = check_game_status_nfl(MagicMock(), game, client=client)

        assert game.end_time == now_val

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_no_matching_game_in_schedule(self, mock_to_et, mock_resolve):
        mock_to_et.return_value = date(2025, 9, 7)

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = 999999
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
        )
        result = check_game_status_nfl(MagicMock(), game, client=client)
        assert result.transition is None

    @patch("sports_scraper.persistence.games.resolve_status_transition")
    @patch("sports_scraper.utils.datetime_utils.to_et_date")
    def test_no_status_change(self, mock_to_et, mock_resolve):
        mock_to_et.return_value = date(2025, 9, 7)
        mock_resolve.return_value = "live"

        client = MagicMock()
        sg = MagicMock()
        sg.game_id = 401547000
        sg.status = "live"
        sg.home_score = None
        sg.away_score = None
        client.fetch_schedule.return_value = [sg]

        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
            status="live",
        )
        result = check_game_status_nfl(MagicMock(), game, client=client)
        assert result.transition is None


class TestProcessGamePbpNfl:
    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_inserts_plays(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 9, 7, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 15

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1", "p2"])

        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
            status="live",
        )
        session = MagicMock()
        result = process_game_pbp_nfl(session, game, client=client)

        assert result.api_calls == 1
        assert result.events_inserted == 15
        mock_upsert.assert_called_once_with(session, game.id, ["p1", "p2"], source="espn_nfl_api")

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_infers_live_from_pregame(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 9, 7, 20, 0, 0, tzinfo=UTC)
        mock_upsert.return_value = 3

        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=["p1"])

        game = _make_game(
            external_ids={"espn_game_id": "401547000"},
            status="pregame",
        )

        with patch("sports_scraper.db.db_models") as mock_db:
            mock_db.GameStatus.pregame.value = "pregame"
            mock_db.GameStatus.live.value = "live"
            result = process_game_pbp_nfl(MagicMock(), game, client=client)

        assert result.transition is not None
        assert result.transition["to"] == "live"
        assert game.status == "live"

    def test_missing_espn_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_pbp_nfl(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_espn_game_id_returns_empty(self):
        game = _make_game(external_ids={"espn_game_id": "bad"})
        result = process_game_pbp_nfl(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.persistence.plays.upsert_plays")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_no_plays_returns_zero_events(self, mock_now, mock_upsert):
        mock_now.return_value = datetime(2025, 9, 7, tzinfo=UTC)
        client = MagicMock()
        client.fetch_play_by_play.return_value = _mock_pbp_payload(plays=[])
        game = _make_game(external_ids={"espn_game_id": "401547000"})
        result = process_game_pbp_nfl(MagicMock(), game, client=client)
        assert result.api_calls == 1
        assert result.events_inserted == 0


class TestProcessGameBoxscoreNfl:
    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_upserts_boxscores(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 9, 7, 23, 0, 0, tzinfo=UTC)

        client = MagicMock()
        tb = [MagicMock()]
        pb = [MagicMock(), MagicMock()]
        client.fetch_boxscore.return_value = _mock_boxscore(
            team_boxscores=tb, player_boxscores=pb,
        )

        game = _make_game(external_ids={"espn_game_id": "401547000"})
        session = MagicMock()
        result = process_game_boxscore_nfl(session, game, client=client)

        assert result.api_calls == 1
        assert result.boxscore_updated is True
        mock_team.assert_called_once_with(session, game.id, tb, source="espn_nfl_api")
        mock_player.assert_called_once_with(session, game.id, pb, source="espn_nfl_api")

    def test_missing_espn_game_id_returns_empty(self):
        game = _make_game(external_ids={})
        result = process_game_boxscore_nfl(MagicMock(), game)
        assert result.api_calls == 0

    def test_invalid_espn_game_id_returns_empty(self):
        game = _make_game(external_ids={"espn_game_id": "bad"})
        result = process_game_boxscore_nfl(MagicMock(), game)
        assert result.api_calls == 0

    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_null_boxscore_not_updated(self, mock_now):
        mock_now.return_value = datetime(2025, 9, 7, tzinfo=UTC)
        client = MagicMock()
        client.fetch_boxscore.return_value = None
        game = _make_game(external_ids={"espn_game_id": "401547000"})
        result = process_game_boxscore_nfl(MagicMock(), game, client=client)
        assert result.boxscore_updated is False

    @patch("sports_scraper.persistence.boxscores.upsert_team_boxscores")
    @patch("sports_scraper.persistence.boxscores.upsert_player_boxscores")
    @patch("sports_scraper.utils.datetime_utils.now_utc")
    def test_empty_team_and_player_lists(self, mock_now, mock_player, mock_team):
        mock_now.return_value = datetime(2025, 9, 7, 23, 0, 0, tzinfo=UTC)

        client = MagicMock()
        client.fetch_boxscore.return_value = _mock_boxscore(
            team_boxscores=[], player_boxscores=[],
        )

        game = _make_game(external_ids={"espn_game_id": "401547000"})
        result = process_game_boxscore_nfl(MagicMock(), game, client=client)
        assert result.boxscore_updated is True
        mock_team.assert_not_called()
        mock_player.assert_not_called()
