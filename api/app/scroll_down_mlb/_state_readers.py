"""Defensive readers for upstream play-dict shapes.

Private helpers for `game_state.compute_timeline`. Upstream play feeds are
inconsistent — same field can arrive as `runners`, `runnersBefore`,
`baseRunners`, etc. The readers in this module accept all known shapes
and return normalized values; everything else is fed `None`.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "EMPTY_BASES",
    "inning_half_from_upstream",
    "normalize_runner_label",
    "read_base_state_after",
    "read_base_state_before",
    "read_count",
    "read_count_before",
    "read_num",
    "read_str",
    "read_upstream_runner_names",
    "read_upstream_runner_names_before",
]


EMPTY_BASES: dict[str, bool] = {"first": False, "second": False, "third": False}


# ---------------------------------------------------------------------------
# Scalar readers
# ---------------------------------------------------------------------------


def read_num(*candidates: Any) -> int | None:
    """Return the first int/float candidate as int, else None.

    Bools are rejected explicitly so `True` doesn't sneak in as `1`.
    """
    for c in candidates:
        if isinstance(c, int | float) and not isinstance(c, bool):
            return int(c)
    return None


def read_str(*candidates: Any) -> str | None:
    """Return the first non-empty stripped string candidate, else None."""
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return None


# ---------------------------------------------------------------------------
# Player-name normalization
# ---------------------------------------------------------------------------


def normalize_runner_label(raw: str | None) -> str | None:
    """Normalize a player name to ``FIRST_INITIAL LAST_NAME`` form.

    The canonical wire format is a single uppercase first-name initial,
    one space, then the uppercased last name (e.g. ``"C CARROLL"``).
    Applied at the data-reader layer so ``TimelineEntry``, the API
    payload, and audit rows all carry the same form.

    Rules:
      * ``None`` and ``""`` pass through unchanged.
      * Periods are stripped (``"C. Carroll"`` → ``"C CARROLL"``).
      * Whitespace tokens drive the split; first-token's first
        character becomes the initial, last token becomes the last name.
        Hyphens inside the last token are preserved (``"Smith-Jones"``
        → ``"SMITH-JONES"``).
      * Multi-part first names take only the first token's initial
        (``"Jo-El Rodriguez"`` → ``"J RODRIGUEZ"``).
      * Single-token input (last name only) is uppercased as-is.
    """
    if raw is None:
        return None
    name = raw.strip()
    if not name:
        return name
    cleaned = name.replace(".", " ")
    parts = cleaned.split()
    if not parts:
        return name
    if len(parts) == 1:
        return parts[0].upper()
    initial = parts[0][0].upper()
    last = parts[-1].upper()
    return f"{initial} {last}"


# ---------------------------------------------------------------------------
# Base-state readers
# ---------------------------------------------------------------------------

_BASE_KEYS: dict[str, str] = {
    "1": "first",
    "2": "second",
    "3": "third",
    "first": "first",
    "second": "second",
    "third": "third",
    "1b": "first",
    "2b": "second",
    "3b": "third",
}


def _read_base_state(raw: Any) -> dict[str, bool] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        if "first" in raw or "second" in raw or "third" in raw:
            return {
                "first": bool(raw.get("first")),
                "second": bool(raw.get("second")),
                "third": bool(raw.get("third")),
            }
    if isinstance(raw, list):
        occupied: dict[str, bool] = {"first": False, "second": False, "third": False}
        for entry in raw:
            key: str | None = None
            if isinstance(entry, str):
                key = entry
            elif isinstance(entry, dict):
                v = entry.get("base")
                if v is None:
                    v = entry.get("on")
                if v is not None:
                    key = str(v)
            if not key:
                continue
            norm = _BASE_KEYS.get(key.lower())
            if norm:
                occupied[norm] = True
        return occupied
    return None


def read_base_state_before(play: dict[str, Any]) -> dict[str, bool] | None:
    """Read "bases before this play" — *Before-keyed fields only.

    Ambiguous keys (`runners`, `runnersOn`, `baseRunners`, `bases`) may
    carry post-play state and are intentionally not consulted here. The
    caller is expected to fall back to the prior play's `situation_after`
    when no explicit before-state key is present.
    """
    return (
        _read_base_state(play.get("baseStateBefore"))
        or _read_base_state(play.get("runnersBefore"))
        or _read_base_state(play.get("baseRunnersBefore"))
        or _read_base_state(play.get("basesBefore"))
    )


def read_base_state_after(play: dict[str, Any]) -> dict[str, bool] | None:
    """Coalesce the many upstream names for "bases after this play"."""
    return (
        _read_base_state(play.get("baseStateAfter"))
        or _read_base_state(play.get("runnersAfter"))
        or _read_base_state(play.get("baseRunnersAfter"))
        or _read_base_state(play.get("basesAfter"))
    )


def read_upstream_runner_names_before(play: dict[str, Any]) -> dict[str, str] | None:
    """Read pre-play runner names — *Before-keyed fields only.

    Mirrors `read_base_state_before`: skips the ambiguous keys
    (`runners`, `runnersOn`, `baseRunners`, `bases`) because they may
    carry post-play snapshots in some vendor feeds.
    """
    return (
        read_upstream_runner_names(play.get("runnersBefore"))
        or read_upstream_runner_names(play.get("baseRunnersBefore"))
    )


def read_count_before(play: dict[str, Any]) -> tuple[int, int] | None:
    """Read pre-play `(balls, strikes)` — *Before-keyed fields only.

    Returns `None` if either is missing. Ambiguous `balls`/`strikes`/
    `count` keys (which may be post-pitch) are intentionally ignored.
    """
    balls = read_num(
        play.get("ballsBefore"),
        (play.get("countBefore") or {}).get("balls"),
    )
    strikes = read_num(
        play.get("strikesBefore"),
        (play.get("countBefore") or {}).get("strikes"),
    )
    if balls is None or strikes is None:
        return None
    return balls, strikes


def read_count(play: dict[str, Any]) -> tuple[int, int] | None:
    """Read `(balls, strikes)` from ambiguous upstream count keys.

    Coalesces top-level `balls`/`strikes`, `ballCount`/`strikeCount`,
    and the object form `count.balls`/`count.strikes`. Returns `None`
    when either component is absent — the caller treats `None` as
    "upstream did not provide count for this play" (no fallback guessing).
    """
    count_obj = play.get("count")
    if not isinstance(count_obj, dict):
        count_obj = {}
    balls = read_num(
        play.get("balls"),
        play.get("ballCount"),
        count_obj.get("balls"),
    )
    strikes = read_num(
        play.get("strikes"),
        play.get("strikeCount"),
        count_obj.get("strikes"),
    )
    if balls is None or strikes is None:
        return None
    return balls, strikes


def read_upstream_runner_names(raw: Any) -> dict[str, str] | None:
    """Extract a `{base: name}` map from any of the runner-list shapes upstream uses.

    All extracted names are normalized to ``FIRST_INITIAL LAST_NAME``
    form via :func:`normalize_runner_label` so downstream consumers
    (timeline, API payload, audit) all receive the canonical label.
    """
    if not raw:
        return None
    if isinstance(raw, dict):
        names: dict[str, str] = {}

        def grab(slot: str, *keys: str) -> None:
            for k in keys:
                v = raw.get(k)
                if isinstance(v, str) and v.strip():
                    label = normalize_runner_label(v)
                    if label:
                        names[slot] = label
                    return
                if isinstance(v, dict):
                    n = v.get("name") or v.get("runnerName") or v.get("playerName")
                    if isinstance(n, str) and n.strip():
                        label = normalize_runner_label(n)
                        if label:
                            names[slot] = label
                        return

        grab("first", "first", "1", "1B")
        grab("second", "second", "2", "2B")
        grab("third", "third", "3", "3B")
        if names:
            return names
    if isinstance(raw, list):
        names = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            base_key = str(entry.get("base") or entry.get("on") or "").lower()
            slot = (
                "first"
                if base_key in ("1", "first", "1b")
                else "second"
                if base_key in ("2", "second", "2b")
                else "third"
                if base_key in ("3", "third", "3b")
                else None
            )
            if not slot:
                continue
            name = entry.get("name") or entry.get("runnerName") or entry.get("playerName")
            if isinstance(name, str) and name.strip():
                label = normalize_runner_label(name)
                if label:
                    names[slot] = label
        if names:
            return names
    return None


# ---------------------------------------------------------------------------
# Inning-half detection
# ---------------------------------------------------------------------------


def inning_half_from_upstream(
    play: dict[str, Any], home_team_abbr: str | None
) -> str | None:
    """Determine "top" or "bottom" of the inning from any upstream signal.

    Tries (in order): explicit `phase`, `periodLabel`, then falls back to
    inferring from `teamAbbreviation` vs `home_team_abbr` (home batting
    means bottom-half).
    """
    phase = (play.get("phase") or "").strip().lower()
    if phase:
        if re.match(r"^(t|top|t1|0)$", phase):
            return "top"
        if re.match(r"^(b|bot|bottom|t2|1)$", phase):
            return "bottom"
        if "top" in phase:
            return "top"
        if "bot" in phase:
            return "bottom"
    label = (play.get("periodLabel") or "").strip().upper()
    if label:
        if label.startswith("TOP") or label.startswith("T ") or label == "T":
            return "top"
        if label.startswith("BOT") or label.startswith("B ") or label == "B":
            return "bottom"
        if re.match(r"^T\d+$", label):
            return "top"
        if re.match(r"^B\d+$", label):
            return "bottom"
    team = (play.get("teamAbbreviation") or "").strip().upper()
    home = (home_team_abbr or "").strip().upper()
    if team and home:
        return "bottom" if team == home else "top"
    return None
