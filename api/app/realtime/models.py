"""Event payload types for the realtime layer.

Channel naming convention:
  games:{league}:{date}     -> list channel (patches for multiple gameIds)
  game:{gameId}:summary     -> single-game summary patch
  game:{gameId}:pbp         -> append-only PBP events
  fairbet:odds              -> minimal fairbet patch stream
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# Channel format validators
_CHANNEL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^games:[A-Z]{2,5}:\d{4}-\d{2}-\d{2}$"),       # games:NBA:2026-03-05
    re.compile(r"^game:\d+:summary$"),                           # game:12345:summary
    re.compile(r"^game:\d+:pbp$"),                               # game:12345:pbp
    re.compile(r"^fairbet:odds$"),                                # fairbet:odds
]

MAX_CHANNELS_PER_CONNECTION = 50


def is_valid_channel(channel: str) -> bool:
    """Return True if channel matches a known format."""
    return any(p.match(channel) for p in _CHANNEL_PATTERNS)


def parse_channel(channel: str) -> dict[str, str]:
    """Parse channel string into its components.

    Returns dict with 'type' plus type-specific keys, or empty dict if invalid.
    """
    if not is_valid_channel(channel):
        return {}

    parts = channel.split(":")
    if parts[0] == "games":
        return {"type": "games_list", "league": parts[1], "date": parts[2]}
    if parts[0] == "game" and parts[2] == "summary":
        return {"type": "game_summary", "game_id": parts[1]}
    if parts[0] == "game" and parts[2] == "pbp":
        return {"type": "game_pbp", "game_id": parts[1]}
    if channel == "fairbet:odds":
        return {"type": "fairbet_odds"}
    return {}


def to_et_date(dt: datetime) -> str:
    """Convert a datetime to America/New_York date string YYYY-MM-DD."""
    return dt.astimezone(EASTERN).strftime("%Y-%m-%d")


@dataclass
class RealtimeEvent:
    """Server -> client event envelope."""

    type: str           # game_patch | pbp_append | fairbet_patch
    channel: str
    seq: int
    payload: dict[str, Any]
    boot_epoch: int = 0
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> dict[str, Any]:
        """Flatten into the wire format expected by the web client."""
        envelope: dict[str, Any] = {
            "type": self.type,
            "channel": self.channel,
            "ts": self.ts,
            "seq": self.seq,
            "boot_epoch": self.boot_epoch,
        }
        # Merge payload keys at the top level (gameId, patch, events, etc.)
        envelope.update(self.payload)
        return envelope
