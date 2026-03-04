"""MLB Statcast-derived advanced stats aggregation.

Fetches playByPlay JSON and aggregates pitch-level data into team-level
advanced batting stats: plate discipline (zone swing/contact rates) and
quality of contact (exit velocity, hard-hit rate, barrel rate).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ..logging import logger
from ..utils.cache import APICache, should_cache_final
from .mlb_constants import (
    BARREL_MIN_EXIT_VELO_MPH,
    CONTACT_CODES,
    HARD_HIT_THRESHOLD_MPH,
    MLB_PBP_URL,
    SWING_CODES,
    ZONE_OUTSIDE,
    ZONE_STRIKE,
)


@dataclass
class TeamStatcastAggregates:
    """Raw Statcast counts for one team in a game."""

    total_pitches: int = 0
    zone_pitches: int = 0
    zone_swings: int = 0
    zone_contact: int = 0
    outside_pitches: int = 0
    outside_swings: int = 0
    outside_contact: int = 0
    balls_in_play: int = 0
    total_exit_velo: float = 0.0
    hard_hit_count: int = 0
    barrel_count: int = 0


# ---------------------------------------------------------------------------
# Pitch classification helpers
# ---------------------------------------------------------------------------


def is_in_zone(zone: int | None) -> bool | None:
    """Classify a pitch zone.

    Returns True for zones 1-9 (strike zone), False for 11-14 (outside),
    None for unknown/missing zones.
    """
    if zone is None:
        return None
    if zone in ZONE_STRIKE:
        return True
    if zone in ZONE_OUTSIDE:
        return False
    return None


def is_swing(pitch_code: str | None) -> bool:
    """Return True if the pitch detail code indicates a swing."""
    if not pitch_code:
        return False
    return pitch_code in SWING_CODES


def is_contact(pitch_code: str | None) -> bool:
    """Return True if the pitch detail code indicates contact was made."""
    if not pitch_code:
        return False
    return pitch_code in CONTACT_CODES


def is_hard_hit(launch_speed: float | None) -> bool:
    """Return True if launch speed qualifies as hard-hit (>= 95 mph)."""
    if launch_speed is None:
        return False
    return launch_speed >= HARD_HIT_THRESHOLD_MPH


def is_barrel(launch_speed: float | None, launch_angle: float | None) -> bool:
    """Return True if the batted ball qualifies as a barrel per MLB formula.

    MLB barrel definition:
    - Exit velocity >= 98 mph
    - At 98 mph: launch angle 26-30 degrees
    - Each additional mph widens the angle window by 2 degrees (1 each side)
    - Caps at 50 degrees on the upper end
    """
    if launch_speed is None or launch_angle is None:
        return False
    if launch_speed < BARREL_MIN_EXIT_VELO_MPH:
        return False

    # Base window at 98 mph: 26-30 degrees
    # Each additional mph above 98 widens by 2 degrees total (1 each direction)
    extra_mph = launch_speed - BARREL_MIN_EXIT_VELO_MPH
    low_angle = 26.0 - extra_mph
    high_angle = min(30.0 + extra_mph, 50.0)

    return low_angle <= launch_angle <= high_angle


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_from_payload(
    payload: dict[str, Any],
) -> dict[str, TeamStatcastAggregates]:
    """Aggregate pitch-level Statcast data from a playByPlay payload.

    Args:
        payload: The raw JSON from the MLB Stats API playByPlay endpoint.

    Returns:
        Dict with "home" and "away" keys mapped to TeamStatcastAggregates.
    """
    home = TeamStatcastAggregates()
    away = TeamStatcastAggregates()

    for at_bat in payload.get("allPlays", []):
        about = at_bat.get("about", {})
        is_top_inning = about.get("isTopInning", True)
        # Top of inning = away team batting; bottom = home team batting
        agg = away if is_top_inning else home

        for event in at_bat.get("playEvents", []):
            if not event.get("isPitch", False):
                continue

            details = event.get("details", {})
            pitch_code = details.get("code")
            zone = event.get("pitchData", {}).get("zone")

            # Try to parse zone as int
            if zone is not None:
                try:
                    zone = int(zone)
                except (ValueError, TypeError):
                    zone = None

            agg.total_pitches += 1

            # Zone classification
            zone_class = is_in_zone(zone)
            if zone_class is True:
                agg.zone_pitches += 1
                if is_swing(pitch_code):
                    agg.zone_swings += 1
                    if is_contact(pitch_code):
                        agg.zone_contact += 1
            elif zone_class is False:
                agg.outside_pitches += 1
                if is_swing(pitch_code):
                    agg.outside_swings += 1
                    if is_contact(pitch_code):
                        agg.outside_contact += 1

            # Quality of contact — only on batted balls with hitData
            hit_data = event.get("hitData")
            if hit_data:
                launch_speed = hit_data.get("launchSpeed")
                launch_angle = hit_data.get("launchAngle")

                if launch_speed is not None:
                    try:
                        launch_speed = float(launch_speed)
                    except (ValueError, TypeError):
                        launch_speed = None

                if launch_angle is not None:
                    try:
                        launch_angle = float(launch_angle)
                    except (ValueError, TypeError):
                        launch_angle = None

                if launch_speed is not None:
                    agg.balls_in_play += 1
                    agg.total_exit_velo += launch_speed

                    if is_hard_hit(launch_speed):
                        agg.hard_hit_count += 1
                    if is_barrel(launch_speed, launch_angle):
                        agg.barrel_count += 1

    return {"home": home, "away": away}


class MLBStatcastFetcher:
    """Fetches playByPlay data and aggregates Statcast stats per team."""

    def __init__(self, client: httpx.Client, cache: APICache) -> None:
        self.client = client
        self._cache = cache

    def fetch_statcast_aggregates(
        self, game_pk: int, game_status: str | None = None
    ) -> dict[str, TeamStatcastAggregates]:
        """Fetch PBP payload and return aggregated Statcast data per team.

        Uses a separate cache key from PBP to avoid interference.
        """
        cache_key = f"mlb_statcast_{game_pk}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("mlb_statcast_using_cache", game_pk=game_pk)
            return aggregate_from_payload(cached)

        url = MLB_PBP_URL.format(game_pk=game_pk)
        logger.info("mlb_statcast_fetch", game_pk=game_pk, url=url)

        response = self.client.get(url)
        response.raise_for_status()
        payload = response.json()

        has_data = bool(payload.get("allPlays"))
        if should_cache_final(has_data, game_status):
            self._cache.put(cache_key, payload)

        return aggregate_from_payload(payload)
