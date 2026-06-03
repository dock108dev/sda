"""Parsing helpers for DataGolf API responses."""

from __future__ import annotations

from datetime import date
from typing import Any

from .models import DGLeaderboardEntry


def parse_leaderboard_entry(p: dict) -> DGLeaderboardEntry:
    # Position: in-play uses "current_pos" (e.g. "T4"), stats uses "position"
    pos_raw = p.get("current_pos") or p.get("position") or p.get("pos")
    position = _safe_int(str(pos_raw).lstrip("T")) if pos_raw else None

    # Score: in-play uses "current_score", stats uses "total"
    _cs = _safe_int(p.get("current_score"))
    total_score = _cs if _cs is not None else _safe_int(p.get("total", p.get("total_score")))

    thru = _safe_int(p.get("thru"))

    # If a player has started (thru > 0) but total_score is still None,
    # they are at even par — DataGolf sometimes omits the score field.
    if total_score is None and thru is not None and thru > 0:
        total_score = 0

    # Determine status: use explicit field, but also detect cut/wd/dq from
    # the position field (DataGolf sometimes uses "MC", "CUT", "WD", "DQ"
    # in current_pos without setting the status field).
    status = _normalize_status(p.get("status", ""), pos_raw)

    return DGLeaderboardEntry(
        dg_id=int(p.get("dg_id", 0)),
        player_name=p.get("player_name", ""),
        position=position,
        total_score=total_score,
        today_score=_safe_int(p.get("today", p.get("today_score"))),
        thru=thru,
        total_strokes=_safe_int(p.get("total_strokes")),
        r1=_safe_int(p.get("R1", p.get("r1"))),
        r2=_safe_int(p.get("R2", p.get("r2"))),
        r3=_safe_int(p.get("R3", p.get("r3"))),
        r4=_safe_int(p.get("R4", p.get("r4"))),
        sg_total=_safe_float(p.get("sg_total")),
        sg_ott=_safe_float(p.get("sg_ott")),
        sg_app=_safe_float(p.get("sg_app")),
        sg_arg=_safe_float(p.get("sg_arg")),
        sg_putt=_safe_float(p.get("sg_putt")),
        status=status,
        win_prob=_safe_float(p.get("win", p.get("win_prob"))),
        top_5_prob=_safe_float(p.get("top_5")),
        top_10_prob=_safe_float(p.get("top_10")),
        make_cut_prob=_safe_float(p.get("make_cut")),
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# Position strings that indicate a missed cut
_CUT_POSITIONS = frozenset({"mc", "cut"})
_WD_POSITIONS = frozenset({"wd", "w/d"})
_DQ_POSITIONS = frozenset({"dq", "dsq"})


def _normalize_status(raw_status: str | None, pos_raw: Any) -> str:
    """Derive a canonical player status from the status field and position.

    DataGolf sometimes encodes cut/wd/dq only in ``current_pos`` (e.g. "MC",
    "CUT", "WD") without setting the ``status`` field.  This function merges
    both signals into one of: ``"active"``, ``"cut"``, ``"wd"``, ``"dq"``.
    """
    s = (raw_status or "").strip().lower()

    # Normalise known synonyms from the status field itself
    if s in ("cut", "mc", "missed cut"):
        return "cut"
    if s in ("wd", "w/d", "withdrew"):
        return "wd"
    if s in ("dq", "dsq", "disqualified"):
        return "dq"
    if s == "active":
        # Explicit "active" — but position may override (API inconsistency)
        pass
    elif s:
        # Unknown non-empty status — treat as active; position may still override
        pass

    # If the status field was empty/missing/active, check position for signals
    if pos_raw is not None:
        pos_str = str(pos_raw).strip().lower()
        if pos_str in _CUT_POSITIONS:
            return "cut"
        if pos_str in _WD_POSITIONS:
            return "wd"
        if pos_str in _DQ_POSITIONS:
            return "dq"

    return "active"


def _safe_float(val: Any) -> float | None:
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None or val == "" or val == "-":
        return None
    if isinstance(val, str) and val.upper() == "E":
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _map_tournament_status(dg_status: str) -> str:
    """Map DataGolf status strings to our convention."""
    s = (dg_status or "").lower().strip()
    if s in ("completed", "complete"):
        return "completed"
    if s in ("in progress", "in_progress", "live"):
        return "in_progress"
    if s in ("canceled", "cancelled"):
        return "cancelled"
    return "scheduled"


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        return None
