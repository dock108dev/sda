"""MLB play-by-play fetching and parsing.

Handles PBP data from the MLB Stats API (statsapi.mlb.com).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayByPlay
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from .mlb_constants import (
    MLB_EVENT_TYPE_MAP,
    MLB_HALF_INNING_BOTTOM_OFFSET,
    MLB_INNING_MULTIPLIER,
    MLB_MIN_EXPECTED_PLAYS,
    MLB_PBP_URL,
)


class MLBPbpFetcher:
    """Fetches and parses play-by-play data from the MLB Stats API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_play_by_play(
        self, game_pk: int, game_status: str | None = None
    ) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game.

        Args:
            game_pk: MLB game primary key.
            game_status: Normalized game status from the DB (e.g. "final").
                Used by should_cache_final to decide whether to persist the
                response.  When None the response is never cached.

        Results are cached to avoid redundant API calls.
        """
        cache_key = f"mlb_pbp_{game_pk}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("mlb_pbp_using_cache", game_pk=game_pk)
            plays = self._parse_pbp_response(cached, game_pk)
            return NormalizedPlayByPlay(source_game_key=str(game_pk), plays=plays)

        url = MLB_PBP_URL.format(game_pk=game_pk)
        logger.info("mlb_pbp_fetch", url=url, game_pk=game_pk)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("mlb_pbp_fetch_error", game_pk=game_pk, error=str(exc))
            return NormalizedPlayByPlay(source_game_key=str(game_pk), plays=[])

        if response.status_code == 404:
            logger.warning("mlb_pbp_not_found", game_pk=game_pk, status=404)
            return NormalizedPlayByPlay(source_game_key=str(game_pk), plays=[])

        if response.status_code != 200:
            logger.warning(
                "mlb_pbp_fetch_failed",
                game_pk=game_pk,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return NormalizedPlayByPlay(source_game_key=str(game_pk), plays=[])

        payload = response.json()
        plays = self._parse_pbp_response(payload, game_pk)

        # Validation: warn if low event count for completed game
        if len(plays) < MLB_MIN_EXPECTED_PLAYS:
            logger.warning(
                "mlb_pbp_low_event_count",
                game_pk=game_pk,
                play_count=len(plays),
                expected_min=MLB_MIN_EXPECTED_PLAYS,
            )

        # Only cache completed game data with actual plays
        if should_cache_final(bool(plays), game_status):
            self._cache.put(cache_key, payload)
            logger.info("mlb_pbp_cached", game_pk=game_pk, play_count=len(plays))
        else:
            logger.info("mlb_pbp_not_cached", game_pk=game_pk, has_data=bool(plays))

        if plays:
            logger.info(
                "mlb_pbp_parsed",
                game_pk=game_pk,
                count=len(plays),
                first_event=plays[0].play_type,
                first_inning=plays[0].quarter,
                last_event=plays[-1].play_type,
                last_inning=plays[-1].quarter,
            )
        else:
            logger.info("mlb_pbp_parsed", game_pk=game_pk, count=0)

        return NormalizedPlayByPlay(source_game_key=str(game_pk), plays=plays)

    def _parse_pbp_response(self, payload: dict, game_pk: int) -> list[NormalizedPlay]:
        """Parse the play-by-play response from the MLB API."""
        plays: list[NormalizedPlay] = []
        all_plays = payload.get("allPlays", [])

        for play in all_plays:
            normalized = self._normalize_play(play, game_pk)
            if normalized:
                plays.append(normalized)

        # Sort by play_index for canonical ordering
        plays.sort(key=lambda p: p.play_index)

        return plays

    def _normalize_play(
        self,
        play: dict[str, Any],
        game_pk: int,
    ) -> NormalizedPlay | None:
        """Normalize a single at-bat/play event from the MLB API."""
        about = play.get("about", {})
        result = play.get("result", {})

        inning = parse_int(about.get("inning"))
        is_top = about.get("isTopInning", True)
        at_bat_index = parse_int(about.get("atBatIndex"))

        if at_bat_index is None:
            return None

        # Build play_index: inning * multiplier + half_inning_offset + atBatIndex
        half_offset = 0 if is_top else MLB_HALF_INNING_BOTTOM_OFFSET
        play_index = (inning or 0) * MLB_INNING_MULTIPLIER + half_offset + at_bat_index

        # Get event type
        event_type = result.get("eventType", "")
        play_type = self._map_event_type(event_type, game_pk)

        # Get batter info (primary player)
        matchup = play.get("matchup", {})
        batter = matchup.get("batter", {})
        pitcher = matchup.get("pitcher", {})
        batter_id = batter.get("id")
        batter_name = batter.get("fullName")

        # Get description
        description = result.get("description")

        # Get scores
        home_score = parse_int(result.get("homeScore"))
        away_score = parse_int(result.get("awayScore"))

        # Determine team abbreviation from half inning
        half_inning = about.get("halfInning", "")

        # Build comprehensive raw_data
        # is_home_team: bottom of inning = home team batting
        raw_data: dict[str, Any] = {
            "at_bat_index": at_bat_index,
            "inning": inning,
            "half_inning": half_inning,
            "is_top_inning": is_top,
            "is_home_team": not is_top,
            "event_type": event_type,
            "event": result.get("event"),
            "rbi": parse_int(result.get("rbi")),
            "batter": {
                "id": batter_id,
                "name": batter_name,
            },
            "pitcher": {
                "id": pitcher.get("id"),
                "name": pitcher.get("fullName"),
            },
            "runners": play.get("runners", []),
            "count": play.get("count", {}),
        }

        # Include pitch data if available
        play_events = play.get("playEvents", [])
        if play_events:
            pitches = []
            for pe in play_events:
                if pe.get("isPitch"):
                    pitch_data = pe.get("pitchData", {})
                    details = pe.get("details", {})
                    pitches.append({
                        "type": details.get("type", {}).get("description"),
                        "speed": pitch_data.get("startSpeed"),
                        "result": details.get("description"),
                        "count": pe.get("count", {}),
                        "hitData": pe.get("hitData"),
                    })
            if pitches:
                raw_data["pitches"] = pitches

        return NormalizedPlay(
            play_index=play_index,
            quarter=inning,
            game_clock=None,  # MLB doesn't have a game clock
            play_type=play_type,
            team_abbreviation=None,  # Set at ingestion if needed
            player_id=str(batter_id) if batter_id else None,
            player_name=batter_name,
            description=description,
            home_score=home_score,
            away_score=away_score,
            raw_data=raw_data,
        )

    def _map_event_type(self, event_type: str, game_pk: int) -> str:
        """Map MLB eventType to normalized event type."""
        if not event_type:
            return "UNKNOWN"

        mapped = MLB_EVENT_TYPE_MAP.get(event_type)
        if mapped:
            return mapped

        logger.warning(
            "mlb_pbp_unknown_event_type",
            game_pk=game_pk,
            event_type=event_type,
        )
        return event_type.upper().replace(" ", "_")
