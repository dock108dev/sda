"""NCAA API play-by-play fetching and parsing.

Fetches PBP data from the NCAA API (ncaa-api.henrygd.me) and normalizes it
into the same NormalizedPlayByPlay format used by the CBB API fetcher.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayByPlay
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from .ncaa_constants import NCAA_EVENT_PATTERNS, NCAA_PBP_URL
from .ncaab_constants import NCAAB_PERIOD_MULTIPLIER


class NCAAPbpFetcher:
    """Fetches and parses play-by-play data from the NCAA API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_play_by_play(
        self,
        ncaa_game_id: str,
        game_status: str | None = None,
        home_abbr: str | None = None,
        away_abbr: str | None = None,
    ) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game.

        Args:
            ncaa_game_id: NCAA game ID (string)
            game_status: Normalized game status from the DB (e.g. "final").
                Used by should_cache_final to decide whether to persist.
            home_abbr: Home team abbreviation (used to set team_abbreviation
                on each play via the isHome boolean from the API).
            away_abbr: Away team abbreviation.

        Returns:
            NormalizedPlayByPlay with all events normalized to canonical format
        """
        # Check cache first
        cache_key = f"ncaa_pbp_{ncaa_game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("ncaa_pbp_using_cache", ncaa_game_id=ncaa_game_id)
            plays = self._parse_periods(
                cached.get("periods", []), ncaa_game_id, home_abbr, away_abbr,
            )
            return NormalizedPlayByPlay(source_game_key=ncaa_game_id, plays=plays)

        url = NCAA_PBP_URL.format(game_id=ncaa_game_id)
        logger.info("ncaa_pbp_fetch", url=url, ncaa_game_id=ncaa_game_id)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("ncaa_pbp_fetch_error", ncaa_game_id=ncaa_game_id, error=str(exc))
            return NormalizedPlayByPlay(source_game_key=ncaa_game_id, plays=[])

        if response.status_code == 404:
            logger.warning("ncaa_pbp_not_found", ncaa_game_id=ncaa_game_id, status=404)
            return NormalizedPlayByPlay(source_game_key=ncaa_game_id, plays=[])

        if response.status_code != 200:
            logger.warning(
                "ncaa_pbp_fetch_failed",
                ncaa_game_id=ncaa_game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return NormalizedPlayByPlay(source_game_key=ncaa_game_id, plays=[])

        payload = response.json()
        periods = payload.get("periods", [])
        plays = self._parse_periods(periods, ncaa_game_id, home_abbr, away_abbr)

        # Only cache final game data with actual plays
        if should_cache_final(bool(plays), game_status):
            self._cache.put(cache_key, payload)
            logger.info(
                "ncaa_pbp_cached",
                ncaa_game_id=ncaa_game_id,
                play_count=len(plays),
                game_status=game_status,
            )

        if plays:
            logger.info(
                "ncaa_pbp_parsed",
                ncaa_game_id=ncaa_game_id,
                count=len(plays),
                first_event=plays[0].play_type,
                first_period=plays[0].quarter,
                last_event=plays[-1].play_type,
                last_period=plays[-1].quarter,
            )
        else:
            logger.info("ncaa_pbp_parsed", ncaa_game_id=ncaa_game_id, count=0)

        return NormalizedPlayByPlay(source_game_key=ncaa_game_id, plays=plays)

    def _parse_periods(
        self,
        periods: list[dict],
        game_id: str,
        home_abbr: str | None = None,
        away_abbr: str | None = None,
    ) -> list[NormalizedPlay]:
        """Parse all periods and their plays into NormalizedPlay objects.

        NCAA API structure (ncaa-api.henrygd.me):
        {
          "periods": [
            {
              "periodNumber": "1",
              "playbyplayStats": [
                {
                  "teamId": "123",
                  "homeScore": "0",
                  "visitorScore": "0",
                  "clock": "20:00",
                  "firstName": "John",
                  "lastName": "Doe",
                  "eventDescription": "Jumper by Doe",
                  "isHome": true,
                  "homeText": "Jumper by Doe",
                  "visitorText": ""
                },
                ...
              ]
            },
            ...
          ]
        }
        """
        all_plays: list[NormalizedPlay] = []

        for period_data in periods:
            period_num = parse_int(period_data.get("periodNumber")) or 0
            plays_list = period_data.get("playbyplayStats", [])

            for seq, play in enumerate(plays_list):
                normalized = self._normalize_ncaa_play(
                    play, period_num, seq, game_id, home_abbr, away_abbr,
                )
                if normalized:
                    all_plays.append(normalized)

        # Sort by play_index for canonical ordering
        all_plays.sort(key=lambda p: p.play_index)

        return all_plays

    def _normalize_ncaa_play(
        self,
        play: dict[str, Any],
        period: int,
        sequence: int,
        game_id: str,
        home_abbr: str | None = None,
        away_abbr: str | None = None,
    ) -> NormalizedPlay | None:
        """Normalize a single play event from the NCAA API."""
        # Build play_index: period * multiplier + sequence
        play_index = period * NCAAB_PERIOD_MULTIPLIER + sequence

        # Extract description: prefer homeText/visitorText over eventDescription
        is_home = play.get("isHome")
        if is_home is True:
            description = play.get("homeText") or play.get("eventDescription") or ""
        elif is_home is False:
            description = play.get("visitorText") or play.get("eventDescription") or ""
        else:
            description = play.get("eventDescription") or ""

        # Classify play type from description text
        play_type = self._classify_play_type(description)

        # Resolve team abbreviation from isHome flag
        team_abbr: str | None = None
        if is_home is True and home_abbr:
            team_abbr = home_abbr
        elif is_home is False and away_abbr:
            team_abbr = away_abbr

        # Player name from firstName + lastName
        first_name = play.get("firstName") or ""
        last_name = play.get("lastName") or ""
        player_name = f"{first_name} {last_name}".strip() or None

        # Scores (all strings in NCAA API)
        home_score = parse_int(play.get("homeScore"))
        away_score = parse_int(play.get("visitorScore"))

        clock = play.get("clock")
        team_id = play.get("teamId")

        # Build raw_data
        raw_data: dict[str, Any] = {
            "sequence": sequence,
            "clock": clock,
            "play_type_raw": play.get("eventDescription", ""),
            "source": "ncaa_api",
        }
        if team_id:
            raw_data["ncaa_team_id"] = team_id
        if is_home is not None:
            raw_data["is_home_team"] = is_home

        return NormalizedPlay(
            play_index=play_index,
            quarter=period,
            game_clock=clock,
            play_type=play_type,
            team_abbreviation=team_abbr,
            player_id=None,  # NCAA API doesn't provide stable player IDs in PBP
            player_name=player_name,
            description=description,
            home_score=home_score,
            away_score=away_score,
            raw_data=raw_data,
        )

    def _classify_play_type(self, description: str) -> str:
        """Classify play type from NCAA API eventDescription text.

        Uses regex patterns from NCAA_EVENT_PATTERNS to match description
        text to canonical play types.
        """
        if not description:
            return "UNKNOWN"

        for pattern, play_type in NCAA_EVENT_PATTERNS:
            if pattern.search(description):
                return play_type

        return "UNKNOWN"
