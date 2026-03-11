"""Game status flag derivation.

Pure function: maps status string to convenience booleans so clients
don't need to duplicate status-parsing logic.
"""

from __future__ import annotations

# Statuses that indicate a game is truly done (no more data updates expected)
FINAL_STATUSES = frozenset({"final", "completed", "official"})
LIVE_STATUSES = frozenset({"in_progress", "live", "halftime"})
PREGAME_STATUSES = frozenset({"scheduled", "pregame", "pre_game", "created"})

# "Truly completed" means final AND no pending corrections — safe to render
# as fully settled (e.g., for bet grading, final box score display).
TRULY_COMPLETED_STATUSES = frozenset({"final", "completed"})

# "Read eligible" means the game has enough data to generate a game flow read.
READ_ELIGIBLE_STATUSES = FINAL_STATUSES


def compute_status_flags(status: str | None) -> dict[str, bool]:
    """Derive convenience boolean flags from a game status string.

    Args:
        status: Raw status string from the games table (e.g., "final", "live").

    Returns:
        Dict with keys: is_live, is_final, is_pregame, is_truly_completed,
        read_eligible. All False when status is None.
    """
    if not status:
        return {
            "is_live": False,
            "is_final": False,
            "is_pregame": False,
            "is_truly_completed": False,
            "read_eligible": False,
        }

    s = status.lower().strip()
    return {
        "is_live": s in LIVE_STATUSES,
        "is_final": s in FINAL_STATUSES,
        "is_pregame": s in PREGAME_STATUSES,
        "is_truly_completed": s in TRULY_COMPLETED_STATUSES,
        "read_eligible": s in READ_ELIGIBLE_STATUSES,
    }
