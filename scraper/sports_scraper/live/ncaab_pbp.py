"""NCAAB play-by-play fetching and parsing.

Handles PBP data from the CBB API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayByPlay
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from .ncaab_constants import (
    CBB_PLAYS_GAME_URL,
    NCAAB_EVENT_TYPE_MAP,
    NCAAB_PERIOD_MULTIPLIER,
)

if TYPE_CHECKING:
    pass


class NCAABPbpFetcher:
    """Fetches and parses play-by-play data from the CBB API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        """Initialize the PBP fetcher.

        Args:
            client: HTTP client for API requests
            cache: Cache for storing API responses
        """
        self.client = client
        self._cache = cache

    def fetch_play_by_play(
        self, game_id: int, game_status: str | None = None,
    ) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game.

        Results are cached to avoid burning API quota on repeated runs.

        Args:
            game_id: CBB game ID
            game_status: Normalized game status from the DB (e.g. "final").
                Used by should_cache_final to decide whether to persist the
                response.  When None the response is never cached.

        Returns:
            NormalizedPlayByPlay with all events normalized to canonical format
        """
        # Check cache first
        cache_key = f"pbp_{game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("ncaab_pbp_using_cache", game_id=game_id)
            plays = self._parse_pbp_response(cached, game_id)
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=plays)

        url = CBB_PLAYS_GAME_URL.format(game_id=game_id)
        logger.info("ncaab_pbp_fetch", url=url, game_id=game_id)

        try:
            response = self.client.get(url)
        except Exception as exc:
            logger.error("ncaab_pbp_fetch_error", game_id=game_id, error=str(exc))
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response.status_code == 404:
            logger.warning("ncaab_pbp_not_found", game_id=game_id, status=404)
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response.status_code != 200:
            logger.warning(
                "ncaab_pbp_fetch_failed",
                game_id=game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        payload = response.json()
        plays = self._parse_pbp_response(payload, game_id)

        # Only cache final game data with actual plays — same gate as boxscore fetchers
        if should_cache_final(bool(plays), game_status):
            self._cache.put(cache_key, payload)
            logger.info("ncaab_pbp_cached", game_id=game_id, play_count=len(plays), game_status=game_status)
        else:
            logger.info(
                "ncaab_pbp_not_cached",
                game_id=game_id,
                game_status=game_status,
                has_data=bool(plays),
            )

        # Log first and last event for debugging
        if plays:
            logger.info(
                "ncaab_pbp_parsed",
                game_id=game_id,
                count=len(plays),
                first_event=plays[0].play_type,
                first_period=plays[0].quarter,
                last_event=plays[-1].play_type,
                last_period=plays[-1].quarter,
            )
        else:
            logger.info("ncaab_pbp_parsed", game_id=game_id, count=0)

        return NormalizedPlayByPlay(source_game_key=str(game_id), plays=plays)

    def _parse_pbp_response(self, payload: list, game_id: int) -> list[NormalizedPlay]:
        """Parse the play-by-play response from the CBB API."""
        plays: list[NormalizedPlay] = []

        for idx, play in enumerate(payload):
            normalized = self._normalize_play(play, idx, game_id)
            if normalized:
                plays.append(normalized)

        # Sort by play_index to ensure canonical ordering
        plays.sort(key=lambda p: p.play_index)

        # Fill gaps where the CBB API omits scores (common on early plays)
        self._fill_missing_scores(plays, game_id)

        return plays

    def _fill_missing_scores(self, plays: list[NormalizedPlay], game_id: int) -> None:
        """Fill missing scores using play-level point data and forward-fill.

        The CBB API sometimes omits homeScore/awayScore on early plays.
        We reconstruct running scores from the ``points`` and ``is_home_team``
        fields in raw_data, syncing to API-provided scores when available.
        """
        home_running = 0
        away_running = 0
        filled = 0

        for play in plays:
            # Add points from this play to running totals (before checking API scores)
            points = play.raw_data.get("points") if play.raw_data else None
            is_home = play.raw_data.get("is_home_team") if play.raw_data else None

            if isinstance(points, int | float) and points > 0 and is_home is not None:
                if is_home:
                    home_running += int(points)
                else:
                    away_running += int(points)

            # If API provided scores, trust them and sync running totals
            if play.home_score is not None and play.away_score is not None:
                home_running = play.home_score
                away_running = play.away_score
            else:
                # Fill from running totals
                play.home_score = home_running
                play.away_score = away_running
                filled += 1

        if filled:
            logger.info(
                "ncaab_pbp_scores_filled",
                game_id=game_id,
                filled_count=filled,
                total_plays=len(plays),
            )

    def _normalize_play(
        self,
        play: dict[str, Any],
        index: int,
        game_id: int,
    ) -> NormalizedPlay | None:
        """Normalize a single play event from the CBB API.

        The CBB API uses various field names. We try multiple keys for each field.
        """
        # Log first play's keys to understand API format (only once per game)
        if index == 0:
            logger.info(
                "ncaab_pbp_play_keys",
                game_id=game_id,
                keys=list(play.keys()),
                sample_play=str(play)[:500],
            )

        # Check if this is a scoring play we want to sample (logged after successful normalization)
        play_type_raw_initial = play.get("playType") or ""
        should_log_scoring_sample = (
            index < 30 and play_type_raw_initial in ("JumpShot", "Layup", "Dunk", "ThreePointer")
        )

        # Extract period/half info - try multiple keys
        period = (
            parse_int(play.get("period"))
            or parse_int(play.get("half"))
            or parse_int(play.get("periodNumber"))
        )

        # Get sequence number if available, otherwise use index
        sequence = (
            parse_int(play.get("sequenceNumber"))
            or parse_int(play.get("playNumber"))
            or parse_int(play.get("eventNumber"))
            or parse_int(play.get("id"))
            or index
        )

        # Build play_index: period * multiplier + sequence for stable ordering
        play_index = (period or 0) * NCAAB_PERIOD_MULTIPLIER + sequence

        # Get timing info - try multiple keys
        clock = (
            play.get("clock")
            or play.get("timeRemaining")
            or play.get("gameClockDisplay")
            or play.get("time")
            or play.get("displayClock")
        )
        elapsed = play.get("elapsed") or play.get("secondsRemaining")

        # Get event type - try multiple keys
        play_type_raw = (
            play.get("playType")
            or play.get("type")
            or play.get("eventType")
            or play.get("typeText")
            or ""
        )
        play_type = self._map_event_type(play_type_raw, game_id)

        # Extract team info - try multiple keys
        team_name = (
            play.get("team")
            or play.get("teamName")
            or play.get("offenseTeam")
            or play.get("teamAbbreviation")
            or play.get("offense")
        )
        # Team might be nested
        if isinstance(play.get("team"), dict):
            team_name = play["team"].get("name") or play["team"].get("abbreviation")

        # Extract player info - try multiple keys
        player_id = (
            play.get("playerId")
            or play.get("athleteId")
            or play.get("participantId")
        )
        player_name = (
            play.get("player")
            or play.get("athleteName")
            or play.get("playerName")
            or play.get("participant")
        )
        # Player might be nested
        if isinstance(play.get("athlete"), dict):
            player_name = play["athlete"].get("displayName") or play["athlete"].get("name")
            player_id = player_id or play["athlete"].get("id")
        if isinstance(play.get("participants"), list) and play["participants"]:
            p = play["participants"][0]
            if isinstance(p, dict):
                player_name = player_name or p.get("displayName") or p.get("name")
                player_id = player_id or p.get("id")

        # Get scores - try multiple keys (avoid `or` since 0 is a valid score)
        _hs = parse_int(play.get("homeScore"))
        home_score = _hs if _hs is not None else parse_int(play.get("homeTeamScore"))
        _as = parse_int(play.get("awayScore"))
        away_score = _as if _as is not None else parse_int(play.get("awayTeamScore"))

        # Get description - try multiple keys
        description = (
            play.get("description")
            or play.get("text")
            or play.get("playText")
            or play.get("scoreText")
            or play.get("displayValue")
            or play.get("shortText")
        )

        # Build raw_data with all source-specific details
        raw_data = {
            "sequence": sequence,
            "clock": clock,
            "elapsed": elapsed,
            "play_type_raw": play_type_raw,
        }
        # Store teamId for team resolution in upsert_plays
        if play.get("teamId"):
            raw_data["cbb_team_id"] = play.get("teamId")
        # Store team name as fallback
        if team_name:
            raw_data["team_name"] = team_name
        # Add any additional fields from the API
        for key in ["shotType", "shotOutcome", "assistPlayerId", "foulType", "shotDistance", "points"]:
            if key in play and play[key] is not None:
                raw_data[key] = play[key]
        # Store home/away flag for score reconstruction
        if play.get("isHomeTeam") is not None:
            raw_data["is_home_team"] = play.get("isHomeTeam")

        normalized = NormalizedPlay(
            play_index=play_index,
            quarter=period,  # Using quarter field for period (NCAA has halves: 1=1st half, 2=2nd half)
            game_clock=clock,
            play_type=play_type,
            team_abbreviation=team_name,  # Using full name since NCAAB has no standard abbreviations
            player_id=str(player_id) if player_id else None,
            player_name=player_name,
            description=description,
            home_score=home_score,
            away_score=away_score,
            raw_data=raw_data,
        )

        # Log scoring play sample after successful normalization
        if should_log_scoring_sample:
            logger.info(
                "ncaab_pbp_scoring_play_sample",
                game_id=game_id,
                index=index,
                # Raw API data
                raw_play_type=play_type_raw_initial,
                raw_team=play.get("team"),
                raw_team_id=play.get("teamId"),
                raw_play_text=play.get("playText"),
                raw_participants=str(play.get("participants"))[:300],
                raw_is_home=play.get("isHomeTeam"),
                # Normalized result
                normalized_play_type=normalized.play_type,
                normalized_team=normalized.team_abbreviation,
                normalized_player=normalized.player_name,
                normalized_description=normalized.description,
            )

        return normalized

    def _map_event_type(self, play_type_raw: str, game_id: int) -> str:
        """Map CBB play type to normalized event type.

        Unknown types are logged and stored with original key.
        """
        if not play_type_raw:
            return "UNKNOWN"

        mapped = NCAAB_EVENT_TYPE_MAP.get(play_type_raw)
        if mapped:
            return mapped

        # Log unknown event type but don't fail
        logger.warning(
            "ncaab_pbp_unknown_event_type",
            game_id=game_id,
            play_type=play_type_raw,
        )
        return play_type_raw.upper().replace(" ", "_")
