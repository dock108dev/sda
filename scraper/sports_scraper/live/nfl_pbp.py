"""NFL play-by-play fetching and parsing.

Handles PBP data from the ESPN NFL summary API.
ESPN returns PBP nested in drives[].plays[] — this module flattens
and normalizes them into the shared NormalizedPlay format.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayByPlay
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from .nfl_constants import (
    NFL_EVENT_TYPE_MAP,
    NFL_MIN_EXPECTED_PLAYS,
    NFL_PERIOD_MULTIPLIER,
    NFL_STATUS_MAP,
    NFL_SUMMARY_URL,
)


class NFLPbpFetcher:
    """Fetches and parses play-by-play data from the ESPN NFL summary API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_play_by_play(self, game_id: int) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game."""
        cache_key = f"pbp_{game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nfl_pbp_using_cache", game_id=game_id)
            plays = self._parse_pbp_response(cached, game_id)
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=plays)

        url = NFL_SUMMARY_URL.format(game_id=game_id)
        logger.info("nfl_pbp_fetch", url=url, game_id=game_id)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("nfl_pbp_fetch_error", game_id=game_id, error=str(exc))
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response.status_code == 404:
            logger.warning("nfl_pbp_not_found", game_id=game_id, status=404)
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response.status_code != 200:
            logger.warning(
                "nfl_pbp_fetch_failed",
                game_id=game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        payload = response.json()
        plays = self._parse_pbp_response(payload, game_id)

        # Check if game is final for caching
        game_status = self._extract_game_status(payload)
        is_final = game_status in ("final", "cancelled")
        if should_cache_final(bool(plays), "OFF" if is_final else "LIVE"):
            self._cache.put(cache_key, payload)
            logger.info("nfl_pbp_cached", game_id=game_id, play_count=len(plays))

        # Validation
        if is_final and len(plays) < NFL_MIN_EXPECTED_PLAYS:
            logger.warning(
                "nfl_pbp_low_event_count",
                game_id=game_id,
                play_count=len(plays),
                expected_min=NFL_MIN_EXPECTED_PLAYS,
            )

        if plays:
            logger.info(
                "nfl_pbp_parsed",
                game_id=game_id,
                count=len(plays),
                first_event=plays[0].play_type,
                last_event=plays[-1].play_type,
            )

        return NormalizedPlayByPlay(source_game_key=str(game_id), plays=plays)

    def _extract_game_status(self, payload: dict) -> str:
        """Extract normalized game status from ESPN summary payload."""
        header = payload.get("header", {})
        competitions = header.get("competitions", [])
        if competitions:
            status_type = competitions[0].get("status", {}).get("type", {}).get("name", "")
            return NFL_STATUS_MAP.get(status_type, "scheduled")
        return "scheduled"

    def _parse_pbp_response(self, payload: dict, game_id: int) -> list[NormalizedPlay]:
        """Parse ESPN summary response into normalized plays.

        ESPN structures PBP as drives containing plays. We flatten
        into a single list with sequential indexing per period.
        """
        plays: list[NormalizedPlay] = []
        drives_data = payload.get("drives", {})

        # drives can be a dict with "previous" list or a list directly
        all_drives: list[dict] = []
        if isinstance(drives_data, dict):
            all_drives = drives_data.get("previous", [])
            current = drives_data.get("current")
            if current:
                all_drives.append(current)
        elif isinstance(drives_data, list):
            all_drives = drives_data

        # Build sequential index per period
        period_counters: dict[int, int] = {}

        for drive in all_drives:
            drive_plays = drive.get("plays", [])
            for play_data in drive_plays:
                normalized = self._normalize_play(play_data, period_counters, game_id)
                if normalized:
                    plays.append(normalized)

        # Sort by play_index
        plays.sort(key=lambda p: p.play_index)

        # Deduplicate on (period, game_clock, play_type, team, description)
        seen: set[tuple] = set()
        deduped: list[NormalizedPlay] = []
        for p in plays:
            key = (p.quarter, p.game_clock, p.play_type, p.team_abbreviation, p.description)
            if key not in seen:
                seen.add(key)
                deduped.append(p)

        if len(deduped) < len(plays):
            logger.info(
                "nfl_pbp_deduped",
                game_id=game_id,
                before=len(plays),
                after=len(deduped),
            )

        return deduped

    def _normalize_play(
        self,
        play_data: dict[str, Any],
        period_counters: dict[int, int],
        game_id: int,
    ) -> NormalizedPlay | None:
        """Normalize a single play from the ESPN API."""
        # Period
        period_data = play_data.get("period", {})
        period = parse_int(period_data.get("number"))
        if period is None:
            return None

        # Increment sequential counter for this period
        seq = period_counters.get(period, 0)
        period_counters[period] = seq + 1
        play_index = period * NFL_PERIOD_MULTIPLIER + seq

        # Game clock
        clock_data = play_data.get("clock", {})
        game_clock = clock_data.get("displayValue")

        # Play type
        play_type_data = play_data.get("type", {})
        play_type_text = play_type_data.get("text", "")
        play_type = NFL_EVENT_TYPE_MAP.get(play_type_text, play_type_text.upper().replace(" ", "_") if play_type_text else "UNKNOWN")

        # Team
        team_abbr = None
        start_data = play_data.get("start", {})
        team_data = start_data.get("team", {})
        if team_data:
            team_abbr = team_data.get("abbreviation")

        # Scores
        home_score = parse_int(play_data.get("homeScore"))
        away_score = parse_int(play_data.get("awayScore"))

        # Description
        description = play_data.get("text")

        # Scoring play flag
        scoring_play = play_data.get("scoringPlay", False)

        raw_data = {
            "espn_play_id": play_data.get("id"),
            "play_type_id": play_type_data.get("id"),
            "play_type_text": play_type_text,
            "scoring_play": scoring_play,
            "yards": play_data.get("statYardage"),
            "start_down": start_data.get("down"),
            "start_distance": start_data.get("distance"),
            "start_yard_line": start_data.get("yardLine"),
        }

        return NormalizedPlay(
            play_index=play_index,
            quarter=period,
            game_clock=game_clock,
            play_type=play_type,
            team_abbreviation=team_abbr,
            player_id=None,
            player_name=None,
            description=description,
            home_score=home_score,
            away_score=away_score,
            raw_data=raw_data,
        )
