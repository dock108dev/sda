"""NHL play-by-play fetching and parsing.

Handles PBP data from the NHL API (api-web.nhle.com).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..logging import logger
from ..models import NormalizedPlay, NormalizedPlayByPlay
from ..utils.cache import APICache, should_cache_final
from ..utils.parsing import parse_int
from ..utils.provider_request import provider_request
from .nhl_constants import (
    NHL_EVENT_TYPE_MAP,
    NHL_MIN_EXPECTED_PLAYS,
    NHL_PBP_URL,
    NHL_PERIOD_MULTIPLIER,
)


class NHLPbpFetcher:
    """Fetches and parses play-by-play data from the NHL API."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        """Initialize the PBP fetcher.

        Args:
            client: HTTP client for API requests
            cache: Cache for storing API responses
        """
        self.client = client
        self._cache = cache

    def fetch_play_by_play(self, game_id: int) -> NormalizedPlayByPlay:
        """Fetch and normalize play-by-play data for a game.

        Results are cached to avoid redundant API calls.

        Args:
            game_id: NHL game ID (e.g., 2025020767)

        Returns:
            NormalizedPlayByPlay with all events normalized to canonical format
        """
        # Check cache first
        cache_key = f"pbp_{game_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("nhl_pbp_using_cache", game_id=game_id)
            plays = self._parse_pbp_response(cached, game_id)
            # Validation for cached data
            game_state = cached.get("gameState", "")
            if game_state == "OFF" and len(plays) < NHL_MIN_EXPECTED_PLAYS:
                logger.warning(
                    "nhl_pbp_low_event_count",
                    game_id=game_id,
                    play_count=len(plays),
                    expected_min=NHL_MIN_EXPECTED_PLAYS,
                    game_state=game_state,
                    source="cache",
                )
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=plays)

        url = NHL_PBP_URL.format(game_id=game_id)
        logger.info("nhl_pbp_fetch", url=url, game_id=game_id)

        try:
            response = provider_request(
                self.client,
                "GET",
                url,
                provider="nhl-api",
                endpoint="playbyplay",
                league="NHL",
                game_id=game_id,
                qps_budget=5.0,
                qps_burst=10,
            )
        except Exception as exc:
            logger.error("nhl_pbp_fetch_error", game_id=game_id, error=str(exc))
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response is None:
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response.status_code == 404:
            logger.warning("nhl_pbp_not_found", game_id=game_id, status=404)
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        if response.status_code != 200:
            logger.warning(
                "nhl_pbp_fetch_failed",
                game_id=game_id,
                status=response.status_code,
                body=response.text[:200] if response.text else "",
            )
            return NormalizedPlayByPlay(source_game_key=str(game_id), plays=[])

        payload = response.json()

        plays = self._parse_pbp_response(payload, game_id)

        # Validation: warn if low event count for completed game
        game_state = payload.get("gameState", "")
        if game_state == "OFF" and len(plays) < NHL_MIN_EXPECTED_PLAYS:
            logger.warning(
                "nhl_pbp_low_event_count",
                game_id=game_id,
                play_count=len(plays),
                expected_min=NHL_MIN_EXPECTED_PLAYS,
                game_state=game_state,
            )

        # Only cache final game data with actual plays — same gate as boxscore fetchers
        if should_cache_final(bool(plays), game_state):
            self._cache.put(cache_key, payload)
            logger.info("nhl_pbp_cached", game_id=game_id, play_count=len(plays), game_state=game_state)
        else:
            logger.info(
                "nhl_pbp_not_cached",
                game_id=game_id,
                game_state=game_state,
                has_data=bool(plays),
            )

        # Log first and last event for debugging
        if plays:
            logger.info(
                "nhl_pbp_parsed",
                game_id=game_id,
                count=len(plays),
                first_event=plays[0].play_type,
                first_period=plays[0].quarter,
                last_event=plays[-1].play_type,
                last_period=plays[-1].quarter,
            )
        else:
            logger.info("nhl_pbp_parsed", game_id=game_id, count=0)

        return NormalizedPlayByPlay(source_game_key=str(game_id), plays=plays)

    def _parse_pbp_response(self, payload: dict, game_id: int) -> list[NormalizedPlay]:
        """Parse the play-by-play response from the NHL API."""
        plays: list[NormalizedPlay] = []
        raw_plays = payload.get("plays", [])

        # Get team info for abbreviation lookup
        home_team_id = payload.get("homeTeam", {}).get("id")
        away_team_id = payload.get("awayTeam", {}).get("id")
        home_abbr = payload.get("homeTeam", {}).get("abbrev")
        away_abbr = payload.get("awayTeam", {}).get("abbrev")

        team_id_to_abbr: dict[int, str] = {}
        if home_team_id and home_abbr:
            team_id_to_abbr[home_team_id] = home_abbr
        if away_team_id and away_abbr:
            team_id_to_abbr[away_team_id] = away_abbr

        # Build player ID to name lookup from rosterSpots
        player_id_to_name: dict[int, str] = {}
        for roster_spot in payload.get("rosterSpots", []):
            player_id = roster_spot.get("playerId")
            first_name = roster_spot.get("firstName", {}).get("default", "")
            last_name = roster_spot.get("lastName", {}).get("default", "")
            if player_id and (first_name or last_name):
                full_name = f"{first_name} {last_name}".strip()
                player_id_to_name[player_id] = full_name

        # Warn if no roster data found
        if not player_id_to_name:
            logger.warning(
                "nhl_pbp_no_roster_data",
                game_id=game_id,
                message="rosterSpots is empty or missing - player names will not be resolved",
            )

        for play in raw_plays:
            normalized = self._normalize_play(play, team_id_to_abbr, player_id_to_name, game_id)
            if normalized:
                plays.append(normalized)

        # Sort by sortOrder to ensure canonical ordering
        plays.sort(key=lambda p: p.play_index)

        # Deduplicate by NHL eventId: the API occasionally repeats the same
        # logical event within a single response (different sortOrder, same
        # eventId).  Cross-run duplicates — same eventId, different sortOrder
        # across two scrape responses — are handled by the (game_id, event_id)
        # unique index at persistence time.  Plays without an eventId fall
        # through unchanged; they cannot be safely deduped without an identity.
        seen_event_ids: set[int] = set()
        deduped: list[NormalizedPlay] = []
        for p in plays:
            if p.event_id is None:
                deduped.append(p)
                continue
            if p.event_id in seen_event_ids:
                continue
            seen_event_ids.add(p.event_id)
            deduped.append(p)
        if len(deduped) < len(plays):
            logger.info(
                "nhl_pbp_deduped",
                game_id=game_id,
                before=len(plays),
                after=len(deduped),
                removed=len(plays) - len(deduped),
            )
        plays = deduped

        return plays

    def _normalize_play(
        self,
        play: dict[str, Any],
        team_id_to_abbr: dict[int, str],
        player_id_to_name: dict[int, str],
        game_id: int,
    ) -> NormalizedPlay | None:
        """Normalize a single play event from the NHL API."""
        # Extract period info
        period_desc = play.get("periodDescriptor", {})
        period = parse_int(period_desc.get("number"))
        period_type = period_desc.get("periodType", "REG")

        # Get sort order as play index (canonical ordering)
        sort_order = parse_int(play.get("sortOrder"))
        if sort_order is None:
            return None

        # Build play_index: period * multiplier + sort_order for stable ordering
        play_index = (period or 0) * NHL_PERIOD_MULTIPLIER + sort_order

        # NHL eventId is the stable per-event identifier; promoted to a
        # first-class field on NormalizedPlay so persistence can key the
        # upsert on (game_id, event_id) instead of (game_id, play_index).
        event_id = parse_int(play.get("eventId"))

        # Get timing info
        time_in_period = play.get("timeInPeriod")
        time_remaining = play.get("timeRemaining")
        game_clock = time_remaining

        # Get event type
        type_desc_key = play.get("typeDescKey", "")
        play_type = self._map_event_type(type_desc_key, game_id)

        # Extract details
        details = play.get("details", {})

        # Get team abbreviation from eventOwnerTeamId
        event_owner_team_id = parse_int(details.get("eventOwnerTeamId"))
        team_abbr = team_id_to_abbr.get(event_owner_team_id) if event_owner_team_id else None

        # Get primary player
        player_id = self._extract_primary_player_id(details, type_desc_key)
        player_name = player_id_to_name.get(player_id) if player_id else None

        # Get scores (only present on goal events)
        home_score = parse_int(details.get("homeScore"))
        away_score = parse_int(details.get("awayScore"))

        # Build raw_data
        raw_data = {
            "event_id": play.get("eventId"),
            "sort_order": sort_order,
            "time_in_period": time_in_period,
            "time_remaining": time_remaining,
            "period_type": period_type,
            "situation_code": play.get("situationCode"),
            "type_code": play.get("typeCode"),
            "type_desc_key": type_desc_key,
            "details": details,
        }

        return NormalizedPlay(
            play_index=play_index,
            quarter=period,
            game_clock=game_clock,
            event_id=event_id,
            play_type=play_type,
            team_abbreviation=team_abbr,
            player_id=str(player_id) if player_id else None,
            player_name=player_name,
            description=self._build_description(
                type_desc_key, details, player_id_to_name, player_name
            ),
            home_score=home_score,
            away_score=away_score,
            raw_data=raw_data,
        )

    def _map_event_type(self, type_desc_key: str, game_id: int) -> str:
        """Map NHL typeDescKey to normalized event type."""
        if not type_desc_key:
            return "UNKNOWN"

        mapped = NHL_EVENT_TYPE_MAP.get(type_desc_key)
        if mapped:
            return mapped

        logger.warning(
            "nhl_pbp_unknown_event_type",
            game_id=game_id,
            type_desc_key=type_desc_key,
        )
        return type_desc_key.upper().replace("-", "_")

    def _extract_primary_player_id(
        self,
        details: dict[str, Any],
        type_desc_key: str,
    ) -> int | None:
        """Extract the primary player ID from event details."""
        if type_desc_key == "goal":
            return parse_int(details.get("scoringPlayerId"))
        elif type_desc_key == "shot-on-goal" or type_desc_key == "missed-shot":
            return parse_int(details.get("shootingPlayerId"))
        elif type_desc_key == "blocked-shot":
            return parse_int(details.get("blockingPlayerId"))
        elif type_desc_key == "hit":
            return parse_int(details.get("hittingPlayerId"))
        elif type_desc_key == "penalty":
            return parse_int(details.get("committedByPlayerId"))
        elif type_desc_key == "faceoff":
            return parse_int(details.get("winningPlayerId"))
        elif type_desc_key == "giveaway" or type_desc_key == "takeaway":
            return parse_int(details.get("playerId"))

        # Generic fallback
        for key in ["playerId", "shootingPlayerId", "scoringPlayerId"]:
            if key in details:
                return parse_int(details.get(key))

        return None

    def _build_description(
        self,
        type_desc_key: str,
        details: dict[str, Any],
        player_id_to_name: dict[int, str] | None = None,
        player_name: str | None = None,
    ) -> str | None:
        """Build a human-readable description from event details.

        ``player_name`` is the primary player for the event (scorer, shooter,
        faceoff winner, penalty taker, etc.).  When supplied it is woven into
        the description so downstream consumers that read only the description
        column (LLM summarizers, full-text search, social-post composers) can
        still identify who did what — matching how NBA play strings already
        embed the player name inline.  When omitted the description falls
        back to the player-less form for backward compatibility.
        """
        if type_desc_key == "goal":
            shot_type = details.get("shotType", "")
            head = f"Goal by {player_name}" if player_name else "Goal"
            parts = [f"{head} ({shot_type})" if shot_type else head]
            # Include assist player names so the pipeline can credit them
            if player_id_to_name:
                assists: list[str] = []
                a1_id = parse_int(details.get("assist1PlayerId"))
                a2_id = parse_int(details.get("assist2PlayerId"))
                if a1_id and a1_id in player_id_to_name:
                    assists.append(player_id_to_name[a1_id])
                if a2_id and a2_id in player_id_to_name:
                    assists.append(player_id_to_name[a2_id])
                if assists:
                    parts.append(f"(assists: {', '.join(assists)})")
            return " ".join(parts)
        elif type_desc_key == "shot-on-goal":
            shot_type = details.get("shotType", "")
            head = f"Shot on goal by {player_name}" if player_name else "Shot on goal"
            return f"{head} ({shot_type})" if shot_type else head
        elif type_desc_key == "missed-shot":
            reason = details.get("reason", "")
            head = f"Missed shot by {player_name}" if player_name else "Missed shot"
            return f"{head} ({reason})" if reason else head
        elif type_desc_key == "blocked-shot":
            blocker_id = parse_int(details.get("blockingPlayerId"))
            blocker = player_id_to_name.get(blocker_id, "") if player_id_to_name and blocker_id else ""
            shooter_id = parse_int(details.get("shootingPlayerId"))
            shooter = player_id_to_name.get(shooter_id, "") if player_id_to_name and shooter_id else ""
            if blocker and shooter:
                return f"Blocked shot ({blocker} blocks {shooter})"
            return "Blocked shot"
        elif type_desc_key == "hit":
            hitter_id = parse_int(details.get("hittingPlayerId"))
            hittee_id = parse_int(details.get("hitteePlayerId"))
            hitter = player_id_to_name.get(hitter_id, "") if player_id_to_name and hitter_id else ""
            hittee = player_id_to_name.get(hittee_id, "") if player_id_to_name and hittee_id else ""
            zone = details.get("zoneCode", "")
            parts = ["Hit"]
            if hitter and hittee:
                parts.append(f"({hitter} on {hittee})")
            if zone:
                parts.append(f"in {zone} zone")
            return " ".join(parts)
        elif type_desc_key == "penalty":
            desc_key = details.get("descKey", "")
            duration = details.get("duration", 2)
            if player_name and desc_key:
                return f"Penalty on {player_name}: {desc_key} ({duration} min)"
            if desc_key:
                return f"Penalty: {desc_key} ({duration} min)"
            if player_name:
                return f"Penalty on {player_name}"
            return "Penalty"
        elif type_desc_key == "giveaway":
            zone = details.get("zoneCode", "")
            head = f"Giveaway by {player_name}" if player_name else "Giveaway"
            return f"{head} ({zone} zone)" if zone else head
        elif type_desc_key == "takeaway":
            zone = details.get("zoneCode", "")
            head = f"Takeaway by {player_name}" if player_name else "Takeaway"
            return f"{head} ({zone} zone)" if zone else head
        elif type_desc_key == "faceoff":
            zone = details.get("zoneCode", "")
            head = f"Faceoff won by {player_name}" if player_name else "Faceoff"
            return f"{head} ({zone} zone)" if zone else head
        elif type_desc_key == "stoppage":
            reason = details.get("reason", "")
            return f"Stoppage: {reason}" if reason else "Stoppage"

        return type_desc_key.replace("-", " ").title()
