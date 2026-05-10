"""Database-backed loader for the Scroll Down MLB deck builder.

Reads `sports_games`, `sports_game_plays`, and `mlb_pitcher_game_stats`
and assembles the upstream-shaped payload that
`service.build_deck_from_upstream` expects (the same shape as the
captured frontend fixtures).

This is the bridge between SDA's normalized schema and the Phase 3
deck builder, which was written to consume the existing frontend BFF
shape verbatim.

Design notes:

* Float `innings_pitched` from the DB (baseball notation: 5.1 = 5⅓ IP)
  is converted to the string form (`"5.1"`) the builder's pitcher walk
  understands.
* `team_id` on plays is resolved to the team abbreviation via a
  per-game team-id → abbreviation map built once at the top of the
  loader.
* `raw_data` JSONB on plays carries any provider-specific extras
  (tier hints, score-before, runner state, etc.). We splat it into
  the upstream play shape so the builder picks up whatever upstream
  ships beyond our normalized columns.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.mlb_advanced import MLBPitcherGameStats
from app.db.sports import (
    GameStatus,
    SportsGame,
    SportsGamePlay,
    SportsTeam,
)


async def load_game_payload(
    session: AsyncSession, game_id: int
) -> Optional[dict[str, Any]]:
    """Load the upstream-shaped payload for one game.

    Returns `None` when the game does not exist or is not MLB.

    The shape mirrors the fixture format in
    `tests/fixtures/scroll_down_mlb/games/`: `{game, plays, mlbPitchers}`.
    The builder accepts unknown extra keys; only the documented ones are
    consumed.
    """
    game_row = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.league),
        )
        .where(SportsGame.id == game_id)
    )
    game: Optional[SportsGame] = game_row.scalar_one_or_none()
    if game is None:
        return None
    if (game.league.code or "").lower() != "mlb":
        return None

    home = game.home_team
    away = game.away_team

    # Build the team-id -> abbreviation map (and team-id -> name) used
    # downstream when normalizing plays. The builder reads
    # `teamAbbreviation` as a string per play, not a foreign key.
    team_abbr: dict[int, str] = {}
    team_name: dict[int, str] = {}
    if home is not None:
        team_abbr[home.id] = home.abbreviation or "HME"
        team_name[home.id] = home.name
    if away is not None:
        team_abbr[away.id] = away.abbreviation or "AWY"
        team_name[away.id] = away.name

    plays_result = await session.execute(
        select(SportsGamePlay)
        .where(SportsGamePlay.game_id == game_id)
        .order_by(SportsGamePlay.play_index)
    )
    plays = list(plays_result.scalars().all())

    pitchers_result = await session.execute(
        select(MLBPitcherGameStats).where(MLBPitcherGameStats.game_id == game_id)
    )
    pitchers = list(pitchers_result.scalars().all())

    return {
        "game": _serialize_game(game, home, away),
        "plays": [_serialize_play(p, team_abbr) for p in plays],
        "mlbPitchers": [_serialize_pitcher(p, team_name) for p in pitchers],
    }


def _serialize_game(
    game: SportsGame,
    home: Optional[SportsTeam],
    away: Optional[SportsTeam],
) -> dict[str, Any]:
    """Game shape consumed by `build_deck_from_upstream`."""
    is_final = GameStatus.is_final_or_post_final_status(game.status)
    is_pregame = (game.status or "").lower() in ("scheduled", "pregame")
    is_live = not is_final and not is_pregame
    return {
        "id": game.id,
        "leagueCode": "MLB",
        "season": game.season,
        "seasonType": game.season_type,
        "gameDate": game.game_date.isoformat() if game.game_date else None,
        "localGameDate": (
            game.local_game_date.isoformat() if game.local_game_date else None
        ),
        "homeTeam": home.name if home else "Home",
        "awayTeam": away.name if away else "Away",
        "homeTeamId": home.id if home else None,
        "awayTeamId": away.id if away else None,
        "homeTeamAbbr": home.abbreviation if home and home.abbreviation else "HME",
        "awayTeamAbbr": away.abbreviation if away and away.abbreviation else "AWY",
        "homeTeamColorLight": home.color_light_hex if home else None,
        "homeTeamColorDark": home.color_dark_hex if home else None,
        "awayTeamColorLight": away.color_light_hex if away else None,
        "awayTeamColorDark": away.color_dark_hex if away else None,
        # Score is consumed by the builder for scoreBefore/scoreAfter
        # propagation when individual plays don't carry the running score.
        # The builder is responsible for keeping it out of the spoiler-safe
        # DTO; this is internal only.
        "homeScore": game.home_score,
        "awayScore": game.away_score,
        "score": (
            {"home": game.home_score, "away": game.away_score}
            if game.home_score is not None and game.away_score is not None
            else None
        ),
        "status": game.status,
        "venue": game.venue,
        "venueName": game.venue,
        "isFinal": is_final,
        "isLive": is_live,
        "isPregame": is_pregame,
        "lastPlayAt": (
            game.last_pbp_at.isoformat() if game.last_pbp_at else None
        ),
        "lastIngestedAt": (
            game.last_ingested_at.isoformat() if game.last_ingested_at else None
        ),
        # The probable-pitcher fields are an upstream concept the SDA
        # schema doesn't directly carry. The builder gracefully degrades
        # to None — the matchup intro just hides them.
        "homeProbablePitcher": None,
        "awayProbablePitcher": None,
    }


def _serialize_play(
    play: SportsGamePlay, team_abbr: dict[int, str]
) -> dict[str, Any]:
    """Play shape matching the upstream `PlayEntry` the builder expects.

    `raw_data` is splatted in last so any extras the scraper captured
    (tier, scoringTeamAbbr, runner state, scoreBefore, etc.) override
    or supplement the normalized columns.
    """
    base: dict[str, Any] = {
        "playIndex": play.play_index,
        "quarter": play.quarter,
        "gameClock": play.game_clock,
        "playType": play.play_type,
        "teamAbbreviation": (
            team_abbr.get(play.team_id) if play.team_id is not None else None
        ),
        "playerName": play.player_name,
        "description": play.description,
        "homeScore": play.home_score,
        "awayScore": play.away_score,
        "score": (
            {"home": play.home_score, "away": play.away_score}
            if play.home_score is not None and play.away_score is not None
            else None
        ),
    }
    extras = play.raw_data or {}
    if isinstance(extras, dict):
        for k, v in extras.items():
            # Don't let raw_data overwrite the normalized identifier.
            if k == "playIndex":
                continue
            base[k] = v
    return base


def _serialize_pitcher(
    pitcher: MLBPitcherGameStats, team_name: dict[int, str]
) -> dict[str, Any]:
    """`mlbPitchers` shape consumed by `compute_pitcher_timeline`.

    The builder parses `inningsPitched` as a string in baseball notation
    (`"5.1"` = 5 innings + 1 out = 16 outs). The DB stores it as a float
    using the same notation, so a `:.1f` format produces the right value.
    """
    return {
        "team": team_name.get(pitcher.team_id) or "",
        "playerName": pitcher.player_name,
        "inningsPitched": f"{pitcher.innings_pitched:.1f}",
        "hits": pitcher.hits,
        "runs": pitcher.runs,
        "earnedRuns": pitcher.earned_runs,
        "baseOnBalls": pitcher.walks,
        "strikeOuts": pitcher.strikeouts,
        "homeRuns": pitcher.home_runs_allowed,
        "isStarter": pitcher.is_starter,
    }


__all__ = ["load_game_payload"]
