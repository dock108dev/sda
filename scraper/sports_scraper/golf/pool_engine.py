"""Pure golf pool scoring and ranking logic."""

from __future__ import annotations

from typing import Any

_ELIGIBLE_STATUSES = frozenset({"active"})


def _parse_rules(rules_json: dict[str, Any] | None) -> dict[str, Any]:
    """Parse rules JSONB into structured config."""
    if not rules_json:
        return {
            "variant": "rvcc",
            "pick_count": 7,
            "count_best": 5,
            "min_cuts_to_qualify": 5,
        }

    variant = rules_json.get("variant", "rvcc").lower()
    defaults = {
        "rvcc": {"pick_count": 7, "count_best": 5, "min_cuts_to_qualify": 5},
        "crestmont": {"pick_count": 6, "count_best": 4, "min_cuts_to_qualify": 4},
    }
    d = defaults.get(variant, defaults["rvcc"])

    return {
        "variant": variant,
        "pick_count": rules_json.get("pick_count", d["pick_count"]),
        "count_best": rules_json.get("count_best", d["count_best"]),
        "min_cuts_to_qualify": rules_json.get("min_cuts_to_qualify", d["min_cuts_to_qualify"]),
    }


def _any_rounds_pending(
    leaderboard: dict[int, dict[str, Any]],
    picks: list[dict[str, Any]],
) -> bool:
    """Check if any picked golfer hasn't completed round 2 yet."""
    for pick in picks:
        gs = leaderboard.get(pick["dg_id"])
        if gs is None:
            return True
        if gs["status"] == "active" and gs.get("r2") is None:
            return True
    return False


def _score_entry(
    entry: dict[str, Any],
    leaderboard: dict[int, dict[str, Any]],
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Score a single entry against live leaderboard data."""
    scored_picks: list[dict[str, Any]] = []
    eligible_picks: list[dict[str, Any]] = []

    for pick in entry["picks"]:
        gs = leaderboard.get(pick["dg_id"])

        if gs is None:
            scored_pick = {
                **pick,
                "status": "unknown",
                "position": None,
                "total_score": None,
                "thru": None,
                "r1": None, "r2": None, "r3": None, "r4": None,
                "made_cut": False,
                "counts_toward_total": False,
                "is_dropped": True,
                "sort_score": None,
            }
        else:
            made_cut = gs["status"] in _ELIGIBLE_STATUSES
            sort_score = gs["total_score"] if gs["total_score"] is not None else 999

            scored_pick = {
                **pick,
                "status": gs["status"],
                "position": gs["position"],
                "total_score": gs["total_score"],
                "thru": gs["thru"],
                "r1": gs.get("r1"),
                "r2": gs.get("r2"),
                "r3": gs.get("r3"),
                "r4": gs.get("r4"),
                "made_cut": made_cut,
                "counts_toward_total": False,
                "is_dropped": True,
                "sort_score": sort_score,
            }

            if made_cut:
                eligible_picks.append(scored_pick)

        scored_picks.append(scored_pick)

    qualified_count = len(eligible_picks)

    if qualified_count >= rules["min_cuts_to_qualify"]:
        qualification_status = "qualified"
    elif _any_rounds_pending(leaderboard, entry["picks"]):
        qualification_status = "pending"
    else:
        qualification_status = "not_qualified"

    eligible_picks.sort(key=lambda p: p["sort_score"] if p["sort_score"] is not None else 999)
    counted = eligible_picks[: rules["count_best"]]

    counted_ids = {p["dg_id"] for p in counted}
    for sp in scored_picks:
        if sp["dg_id"] in counted_ids:
            sp["counts_toward_total"] = True
            sp["is_dropped"] = False

    aggregate = None
    if counted:
        scores = [p["total_score"] for p in counted if p["total_score"] is not None]
        if scores:
            aggregate = sum(scores)

    is_complete = all(
        p["thru"] == 18 or p["thru"] is None
        for p in counted
    ) and qualification_status != "pending"

    return {
        "entry_id": entry["entry_id"],
        "email": entry["email"],
        "entry_name": entry["entry_name"],
        "picks": scored_picks,
        "aggregate_score": aggregate,
        "qualified_golfers_count": qualified_count,
        "counted_golfers_count": len(counted),
        "qualification_status": qualification_status,
        "is_complete": is_complete,
        "rank": None,
        "is_tied": False,
    }


def _rank_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign ranks to scored entries."""
    qualified = [e for e in entries if e["qualification_status"] == "qualified"]
    pending = [e for e in entries if e["qualification_status"] == "pending"]
    not_qualified = [e for e in entries if e["qualification_status"] == "not_qualified"]

    qualified.sort(key=lambda e: e["aggregate_score"] if e["aggregate_score"] is not None else 9999)

    rank = 1
    for i, entry in enumerate(qualified):
        if i > 0 and entry["aggregate_score"] == qualified[i - 1]["aggregate_score"]:
            entry["rank"] = qualified[i - 1]["rank"]
            entry["is_tied"] = True
            qualified[i - 1]["is_tied"] = True
        else:
            entry["rank"] = rank
        rank = i + 2

    for entry in pending:
        entry["rank"] = rank
        rank += 1

    for entry in not_qualified:
        entry["rank"] = None

    return qualified + pending + not_qualified


# ---------------------------------------------------------------------------
# Materialized result persistence
# ---------------------------------------------------------------------------
