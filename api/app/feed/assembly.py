"""Feed response, state, and source identity assembly helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.db.sports import GameStatus, SportsGame, SportsGamePlay
from app.routers.sports.common import serialize_player_stat, serialize_team_stat
from app.routers.sports.schemas.common import PlayEntry, ScoreObject

from .basketball_context import BasketballCardContext
from .football_context import FootballCardContext
from .mlb_context import MlbCardContext
from .nhl_context import NhlCardContext
from .schemas import (
    CardFeedResponse,
    CardFeedStatus,
    CardGameMetadata,
    CardSectionLeadIn,
    CardSituation,
    CardTeam,
    FeedGenerationStatus,
    NarrativeCard,
)

SUPPORTED_SPORTS: dict[str, str] = {
    "MLB": "baseball",
    "NHL": "hockey",
    "NBA": "basketball",
    "NCAAB": "basketball",
    "NFL": "football",
    "NCAAF": "football",
}


def _source_hash_for_card_feed(
    game: SportsGame,
    league: str,
    sorted_plays: list[SportsGamePlay],
) -> str:
    last_play = sorted_plays[-1] if sorted_plays else None
    digest_input = {
        "gameId": game.id,
        "league": league,
        "status": game.status,
        "playCount": len(sorted_plays),
        "lastPlayIndex": last_play.play_index if last_play else None,
        "homeScore": getattr(last_play, "home_score", None),
        "awayScore": getattr(last_play, "away_score", None),
        "lastPbpAt": getattr(game, "last_pbp_at", None),
        "lastIngestedAt": getattr(game, "last_ingested_at", None),
        "plays": [
            {
                "playIndex": play.play_index,
                "period": play.quarter,
                "clock": play.game_clock,
                "type": play.play_type,
                "team": play.team.abbreviation if play.team else None,
                "player": play.player_name,
                "description": play.description,
                "homeScore": play.home_score,
                "awayScore": play.away_score,
                "raw": play.raw_data,
            }
            for play in sorted_plays
        ],
    }
    raw = json.dumps(digest_input, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def _response(
    *,
    game: SportsGame,
    sport: str,
    league: str,
    feed_status: CardFeedStatus,
    cards: list[NarrativeCard],
    last_play_index: int | None,
    sections: list[CardSectionLeadIn] | None = None,
    validation_issues: list[str] | None = None,
) -> CardFeedResponse:
    payoff = _payoff_data(game)
    return CardFeedResponse(
        game=CardGameMetadata(
            gameId=game.id,
            sport=sport,
            league=league,
            status=game.status,
            homeTeam=game.home_team.name if game.home_team else None,
            awayTeam=game.away_team.name if game.away_team else None,
            homeTeamId=game.home_team.id if game.home_team else None,
            awayTeamId=game.away_team.id if game.away_team else None,
            homeTeamAbbr=game.home_team.abbreviation if game.home_team else None,
            awayTeamAbbr=game.away_team.abbreviation if game.away_team else None,
            score=payoff["score"],
        ),
        generation=FeedGenerationStatus(
            status=feed_status,
            cardCount=len(cards),
            lastPlayIndex=last_play_index,
            generatedAt=datetime.now(UTC) if cards else None,
            isStale=feed_status is CardFeedStatus.stale_regenerating,
            validationIssues=validation_issues or [],
        ),
        sections=sections or [],
        teamStats=payoff["team_stats"],
        playerStats=payoff["player_stats"],
        cards=cards,
    )

def _payoff_data(game: SportsGame) -> dict[str, object]:
    league_code = _league_code(game)
    score = None
    home_score = getattr(game, "home_score", None)
    away_score = getattr(game, "away_score", None)
    if home_score is not None and away_score is not None:
        score = ScoreObject(home=home_score, away=away_score)

    return {
        "score": score,
        "team_stats": [
            serialize_team_stat(boxscore, league_code=league_code)
            for boxscore in getattr(game, "team_boxscores", [])
        ],
        "player_stats": [
            serialize_player_stat(boxscore, league_code=league_code)
            for boxscore in getattr(game, "player_boxscores", [])
        ],
    }

def _initial_status(
    game: SportsGame,
    league: str,
    sorted_plays: list[SportsGamePlay],
) -> CardFeedStatus:
    if league not in SUPPORTED_SPORTS:
        return CardFeedStatus.unsupported_sport
    if not sorted_plays:
        return CardFeedStatus.no_pbp_yet
    if game.status == GameStatus.recap_pending.value:
        return CardFeedStatus.generation_pending
    if game.status == GameStatus.recap_failed.value:
        return CardFeedStatus.validation_blocked
    if game.status == GameStatus.live.value and _is_stale(game):
        return CardFeedStatus.stale_regenerating
    return CardFeedStatus.ready

def _state_issues(feed_status: CardFeedStatus) -> list[str]:
    if feed_status is CardFeedStatus.validation_blocked:
        return ["Card validation is blocked by upstream game state."]
    return []

def _is_stale(game: SportsGame) -> bool:
    last_pbp_at = getattr(game, "last_pbp_at", None)
    last_ingested_at = getattr(game, "last_ingested_at", None)
    return bool(last_pbp_at and last_ingested_at and last_pbp_at > last_ingested_at)

def _league_code(game: SportsGame) -> str:
    return (game.league.code if game.league else "UNKNOWN").upper()

def _plays_through(
    sorted_plays: list[SportsGamePlay],
    through_play_index: int | None,
) -> list[SportsGamePlay]:
    if through_play_index is None:
        return sorted_plays
    return [play for play in sorted_plays if play.play_index <= through_play_index]

def _team_for_play(game: SportsGame, abbreviation: str | None) -> CardTeam:
    home_abbr = game.home_team.abbreviation if game.home_team else None
    away_abbr = game.away_team.abbreviation if game.away_team else None
    if abbreviation and abbreviation == home_abbr:
        return CardTeam(abbreviation=abbreviation, name=game.home_team.name, side="home")
    if abbreviation and abbreviation == away_abbr:
        return CardTeam(abbreviation=abbreviation, name=game.away_team.name, side="away")
    return CardTeam(abbreviation=abbreviation, side="unknown")

def _situation(
    play: PlayEntry,
    mlb_context: MlbCardContext | None = None,
    nhl_context: NhlCardContext | None = None,
    basketball_context: BasketballCardContext | None = None,
    football_context: FootballCardContext | None = None,
) -> CardSituation:
    if mlb_context is not None:
        return CardSituation(summary=mlb_context.summary, raw=mlb_context.raw)
    if nhl_context is not None:
        return CardSituation(summary=nhl_context.summary, raw=nhl_context.raw)
    if basketball_context is not None:
        return CardSituation(summary=basketball_context.summary, raw=basketball_context.raw)
    if football_context is not None:
        return CardSituation(summary=football_context.summary, raw=football_context.raw)
    raw = play.situation_before or play.situation_after
    summary = None
    if isinstance(raw, dict):
        display = raw.get("display")
        if isinstance(display, dict):
            summary = display.get("headline")
    if not summary:
        summary = play.time_label or play.period_label
    return CardSituation(summary=summary, raw=raw)

def _source_play_id(
    play: PlayEntry,
    football_context: FootballCardContext | None = None,
    provider_source_id: str | None = None,
) -> str:
    if football_context and football_context.source_play_id:
        return football_context.source_play_id
    if provider_source_id:
        return provider_source_id
    return str(play.play_index)

def _provider_source_play_id(play: SportsGamePlay) -> str | None:
    if play.event_id is not None:
        return str(play.event_id)
    raw_data = play.raw_data if isinstance(play.raw_data, dict) else {}
    for key in ("sourceEventId", "source_event_id", "eventId", "event_id", "providerEventId"):
        value = raw_data.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool):
            source_id = str(value).strip()
            if source_id:
                return source_id
    return None

