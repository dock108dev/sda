"""ActiveGamesResolver: query games by lifecycle window state.

Computes window_state at query time (never stored) so results are always fresh.
Window states:
- PRE:  scheduled/pregame game within pregame_window_hours of game_date
- IN:   live game
- POST: final game within postgame_window_hours of end_time
- NONE: game outside any active window
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from sqlalchemy import case, exists, literal_column, not_, or_
from sqlalchemy.orm import Session

from ..config_sports import LEAGUE_CONFIG, LeagueConfig
from ..db import db_models
from ..logging import logger
from ..utils.datetime_utils import now_utc

WindowState = Literal["PRE", "IN", "POST", "NONE"]

# Default windows used when no league-specific config is available
_DEFAULT_PREGAME_HOURS = LeagueConfig(code="", display_name="").pregame_window_hours
_DEFAULT_POSTGAME_HOURS = LeagueConfig(code="", display_name="").postgame_window_hours
_DEFAULT_PBP_STALE_MINUTES = 4


class ActiveGamesResolver:
    """Resolves which games need attention right now.

    All queries compute window_state inline via SQL CASE so results
    are never stale. Designed for indexed scans over ~50-100 active games.
    """

    def __init__(
        self,
        pregame_hours: int = _DEFAULT_PREGAME_HOURS,
        postgame_hours: int = _DEFAULT_POSTGAME_HOURS,
        pbp_stale_minutes: int = _DEFAULT_PBP_STALE_MINUTES,
    ) -> None:
        self.pregame_hours = pregame_hours
        self.postgame_hours = postgame_hours
        self.pbp_stale_minutes = pbp_stale_minutes

    @staticmethod
    def _window_state_expression(
        pregame_hours: int = _DEFAULT_PREGAME_HOURS,
        postgame_hours: int = _DEFAULT_POSTGAME_HOURS,
    ):
        """Build a SQL CASE expression that computes window_state inline."""
        now = now_utc()
        return case(
            # POST: final game with end_time within postgame window
            (
                (db_models.SportsGame.status == db_models.GameStatus.final.value)
                & (db_models.SportsGame.end_time.isnot(None))
                & (db_models.SportsGame.end_time > now - timedelta(hours=postgame_hours)),
                literal_column("'POST'"),
            ),
            # IN: currently live
            (
                db_models.SportsGame.status == db_models.GameStatus.live.value,
                literal_column("'IN'"),
            ),
            # PRE: scheduled or pregame within pregame window
            (
                (
                    db_models.SportsGame.status.in_([
                        db_models.GameStatus.scheduled.value,
                        db_models.GameStatus.pregame.value,
                    ])
                )
                & (db_models.SportsGame.game_date.isnot(None))
                & (db_models.SportsGame.game_date < now + timedelta(hours=pregame_hours)),
                literal_column("'PRE'"),
            ),
            else_=literal_column("'NONE'"),
        )

    @staticmethod
    def _active_window_filter(
        pregame_hours: int = _DEFAULT_PREGAME_HOURS,
        postgame_hours: int = _DEFAULT_POSTGAME_HOURS,
    ):
        """Build a SQL OR filter that matches only games in an active window.

        Mirrors the CASE branches in _window_state_expression so the DB can
        use indexes on status/game_date/end_time and avoid loading historical
        final games that fall outside the postgame window.
        """
        now = now_utc()
        return or_(
            # POST: final game with end_time within postgame window
            (
                (db_models.SportsGame.status == db_models.GameStatus.final.value)
                & (db_models.SportsGame.end_time.isnot(None))
                & (db_models.SportsGame.end_time > now - timedelta(hours=postgame_hours))
            ),
            # IN: currently live
            db_models.SportsGame.status == db_models.GameStatus.live.value,
            # PRE: scheduled/pregame within pregame window
            (
                db_models.SportsGame.status.in_([
                    db_models.GameStatus.scheduled.value,
                    db_models.GameStatus.pregame.value,
                ])
                & (db_models.SportsGame.game_date.isnot(None))
                & (db_models.SportsGame.game_date < now + timedelta(hours=pregame_hours))
            ),
        )

    def get_active_games(
        self,
        session: Session,
        league_code: str | None = None,
    ) -> list[tuple[db_models.SportsGame, str]]:
        """Return games in any active window with their computed window_state.

        Args:
            session: DB session
            league_code: Optional filter by league

        Returns:
            List of (game, window_state) tuples where window_state is PRE/IN/POST
        """
        ws = self._window_state_expression(self.pregame_hours, self.postgame_hours)
        query = (
            session.query(db_models.SportsGame, ws.label("window_state"))
            .filter(self._active_window_filter(self.pregame_hours, self.postgame_hours))
        )

        if league_code:
            league_id = (
                session.query(db_models.SportsLeague.id)
                .filter(db_models.SportsLeague.code == league_code)
                .scalar()
            )
            if league_id:
                query = query.filter(db_models.SportsGame.league_id == league_id)

        return query.all()

    def get_games_needing_pbp(
        self,
        session: Session,
    ) -> list[db_models.SportsGame]:
        """Return pregame/live games where PBP data is stale.

        Only includes leagues with live_pbp_enabled=True.
        A game needs PBP if last_pbp_at is NULL or older than pbp_stale_minutes.
        """
        now = now_utc()
        stale_threshold = now - timedelta(minutes=self.pbp_stale_minutes)

        # Get league IDs where live PBP is enabled
        enabled_leagues = [
            code for code, cfg in LEAGUE_CONFIG.items() if cfg.live_pbp_enabled
        ]
        if not enabled_leagues:
            return []

        league_ids = (
            session.query(db_models.SportsLeague.id)
            .filter(db_models.SportsLeague.code.in_(enabled_leagues))
            .all()
        )
        league_id_list = [lid for (lid,) in league_ids]
        if not league_id_list:
            return []

        # Include pregame/live games with stale PBP, plus final games
        # that need PBP backfill (missed live window or incomplete data).
        has_plays = exists().where(
            db_models.SportsGamePlay.game_id == db_models.SportsGame.id
        )

        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id.in_(league_id_list),
                or_(
                    # Normal: pregame/live with stale PBP
                    (
                        db_models.SportsGame.status.in_([
                            db_models.GameStatus.pregame.value,
                            db_models.GameStatus.live.value,
                        ])
                        & or_(
                            db_models.SportsGame.last_pbp_at.is_(None),
                            db_models.SportsGame.last_pbp_at < stale_threshold,
                        )
                    ),
                    # Backfill: final games from last 48 hours with no play data at all
                    (
                        (db_models.SportsGame.status == db_models.GameStatus.final.value)
                        & (db_models.SportsGame.game_date > now - timedelta(hours=48))
                        & not_(has_plays)
                    ),
                    # Backfill: final games from last 48 hours where PBP was captured
                    # before the game was finalized (incomplete due to rain delays,
                    # stale timeout, etc). Only triggers when PBP hasn't been
                    # refreshed in the last hour, preventing repeated re-fetches
                    # from routine boxscore updates.
                    (
                        (db_models.SportsGame.status == db_models.GameStatus.final.value)
                        & (db_models.SportsGame.game_date > now - timedelta(hours=48))
                        & (db_models.SportsGame.home_score.isnot(None))
                        & (db_models.SportsGame.last_pbp_at.isnot(None))
                        & (db_models.SportsGame.last_boxscore_at.isnot(None))
                        & (db_models.SportsGame.last_pbp_at < db_models.SportsGame.last_boxscore_at)
                        & (db_models.SportsGame.last_pbp_at < now - timedelta(hours=1))
                    ),
                ),
            )
            .order_by(db_models.SportsGame.game_date.asc().nullslast())
            .all()
        )

        logger.debug("games_needing_pbp", count=len(games))
        return games

    def get_games_needing_boxscore(
        self,
        session: Session,
    ) -> list[db_models.SportsGame]:
        """Return live and recently-final games within postgame window where boxscore data is stale.

        Only includes leagues with live_boxscore_enabled=True.
        A game needs a boxscore refresh if last_boxscore_at is NULL or older
        than pbp_stale_minutes (same staleness window as PBP).
        """
        now = now_utc()
        stale_threshold = now - timedelta(minutes=self.pbp_stale_minutes)

        enabled_leagues = [
            code for code, cfg in LEAGUE_CONFIG.items() if cfg.live_boxscore_enabled
        ]
        if not enabled_leagues:
            return []

        league_ids = (
            session.query(db_models.SportsLeague.id)
            .filter(db_models.SportsLeague.code.in_(enabled_leagues))
            .all()
        )
        league_id_list = [lid for (lid,) in league_ids]
        if not league_id_list:
            return []

        # Include live/recently-final with stale boxscores, plus final games
        # that never got any boxscore data (backfill after missed live window).
        has_boxscores = exists().where(
            db_models.SportsTeamBoxscore.game_id == db_models.SportsGame.id
        )

        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.league_id.in_(league_id_list),
                or_(
                    # Normal: live or recently-final with stale boxscore
                    (
                        or_(
                            db_models.SportsGame.status == db_models.GameStatus.live.value,
                            (
                                (db_models.SportsGame.status == db_models.GameStatus.final.value)
                                & (db_models.SportsGame.end_time.isnot(None))
                                & (db_models.SportsGame.end_time > now - timedelta(hours=self.postgame_hours))
                            ),
                        )
                        & or_(
                            db_models.SportsGame.last_boxscore_at.is_(None),
                            db_models.SportsGame.last_boxscore_at < stale_threshold,
                        )
                    ),
                    # Backfill: final games from last 48 hours with no boxscore data at all
                    (
                        (db_models.SportsGame.status == db_models.GameStatus.final.value)
                        & (db_models.SportsGame.game_date > now - timedelta(hours=48))
                        & not_(has_boxscores)
                    ),
                ),
            )
            .order_by(db_models.SportsGame.game_date.asc().nullslast())
            .all()
        )

        logger.debug("games_needing_boxscore", count=len(games))
        return games

    def get_games_needing_social(
        self,
        session: Session,
    ) -> list[tuple[int, int]]:
        """Return (game_id, team_id) pairs for games in active windows.

        Returns unique team IDs across all active games so social collection
        can be dispatched per-team without duplicates.  Also includes final
        games that never got any social posts (backfill).
        """
        active = self.get_active_games(session)
        seen_teams: set[int] = set()
        pairs: list[tuple[int, int]] = []

        for game, _ws in active:
            for team_id in (game.home_team_id, game.away_team_id):
                if team_id not in seen_teams:
                    seen_teams.add(team_id)
                    pairs.append((game.id, team_id))

        # Backfill: final games from last 48 hours with no social posts at all
        now = now_utc()
        has_social = exists().where(
            db_models.TeamSocialPost.game_id == db_models.SportsGame.id
        )
        backfill_games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.status == db_models.GameStatus.final.value,
                db_models.SportsGame.game_date > now - timedelta(hours=48),
                not_(has_social),
            )
            .all()
        )
        for game in backfill_games:
            for team_id in (game.home_team_id, game.away_team_id):
                if team_id not in seen_teams:
                    seen_teams.add(team_id)
                    pairs.append((game.id, team_id))

        logger.debug("games_needing_social", pairs=len(pairs), unique_teams=len(seen_teams))
        return pairs

    def get_games_needing_odds(
        self,
        session: Session,
    ) -> list[db_models.SportsGame]:
        """Return games that need odds updates.

        Includes:
        - pregame games (active odds)
        - recently-final games within 2 hours (closing line capture)

        Live games are excluded to preserve pre-game closing lines.
        """
        now = now_utc()
        closing_line_cutoff = now - timedelta(hours=2)

        games = (
            session.query(db_models.SportsGame)
            .filter(
                or_(
                    # Pregame games need odds updates
                    db_models.SportsGame.status.in_([
                        db_models.GameStatus.pregame.value,
                    ]),
                    # Recently-final games need closing line
                    (
                        (db_models.SportsGame.status == db_models.GameStatus.final.value)
                        & (db_models.SportsGame.end_time.isnot(None))
                        & (db_models.SportsGame.end_time > closing_line_cutoff)
                    ),
                )
            )
            .order_by(db_models.SportsGame.game_date.asc().nullslast())
            .all()
        )

        logger.debug("games_needing_odds", count=len(games))
        return games
