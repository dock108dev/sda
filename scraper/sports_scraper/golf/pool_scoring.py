"""Golf pool scoring — reads live data from DB and writes materialized results.

This is a lightweight DB-backed scoring pipeline that:
1. Auto-activates pools whose ``scoring_starts_at`` has passed
2. Auto-locks pools whose ``entry_deadline`` has passed
3. Loads entries + picks from ``golf_pool_entries`` / ``golf_pool_entry_picks``
4. Loads live leaderboard data from ``golf_leaderboard``
5. Runs the pure scoring engine (ported from ``api.app.services.golf_pool_scoring``)
6. Upserts materialized results to ``golf_pool_entry_scores`` / ``golf_pool_entry_score_players``

Auto-activation:
    Pools store ``scoring_starts_at`` in ``rules_json``.  When the current
    UTC time passes that threshold, the pool is transitioned from any
    pre-live status (draft/open/locked) to ``status='live'`` with
    ``scoring_enabled=TRUE``.  Pools whose ``entry_deadline`` has passed
    are also auto-locked (entries blocked by the API deadline check, but
    the status column is updated for clarity).

Uses ``sqlalchemy.text()`` for raw SQL following the ``persistence.py`` pattern.

Column naming conventions (from the Alembic migration):
- ``golf_pools``: uses ``rules_json`` (JSONB), no ``last_scored_at``
- ``golf_pool_entry_picks``: uses ``player_name_snapshot`` (not ``player_name``)
- ``golf_pool_entry_score_players``: uses ``*_snapshot`` suffix for
  ``player_name_snapshot``, ``status_snapshot``, ``position_snapshot``,
  ``thru_snapshot``, ``total_score_snapshot``, ``made_cut_snapshot``.
  Round columns ``r1``-``r4`` have NO suffix.
- ``golf_pool_entry_scores``: unique on ``entry_id`` (not ``pool_id, entry_id``)
- ``golf_pool_entry_score_players``: unique on ``(entry_id, dg_id)``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from ..logging import logger

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Eligible statuses — only "active" golfers count toward scoring
# ---------------------------------------------------------------------------

_ELIGIBLE_STATUSES = frozenset({"active"})

# Statuses eligible for auto-lock (entry_deadline passed)
_PRE_LOCK_STATUSES = ("draft", "open")

# Statuses eligible for auto-activation (scoring_starts_at passed)
_PRE_LIVE_STATUSES = ("draft", "open", "locked")


# ---------------------------------------------------------------------------
# Auto-activation helpers
# ---------------------------------------------------------------------------


def _auto_activate_pools(session: Session) -> list[dict[str, Any]]:
    """Auto-lock and auto-activate pools based on timestamps in rules_json.

    1. Pools in draft/open whose ``entry_deadline`` has passed → locked
    2. Pools in draft/open/locked whose ``rules_json->scoring_starts_at``
       has passed → live + scoring_enabled

    Returns list of activation events for logging.
    """
    now = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []

    # --- Auto-lock: entry_deadline has passed ---
    rows = session.execute(
        text("""
            SELECT id, code, status, entry_deadline
            FROM golf_pools
            WHERE status IN ('draft', 'open')
              AND entry_deadline IS NOT NULL
              AND entry_deadline <= :now
        """),
        {"now": now},
    ).fetchall()

    for r in rows:
        pool_id, code, old_status = r[0], r[1], r[2]
        session.execute(
            text("""
                UPDATE golf_pools
                SET status = 'locked', updated_at = NOW()
                WHERE id = :id
            """),
            {"id": pool_id},
        )
        events.append({
            "pool_id": pool_id,
            "code": code,
            "action": "auto_locked",
            "from_status": old_status,
        })
        logger.info(
            "golf_pool_auto_locked",
            pool_id=pool_id,
            code=code,
            from_status=old_status,
            entry_deadline=str(r[3]),
        )

    # --- Auto-activate: scoring_starts_at has passed ---
    rows = session.execute(
        text("""
            SELECT id, code, status, rules_json
            FROM golf_pools
            WHERE status IN ('draft', 'open', 'locked')
              AND rules_json IS NOT NULL
              AND rules_json->>'scoring_starts_at' IS NOT NULL
        """),
    ).fetchall()

    for r in rows:
        pool_id, code, old_status, rules_json = r[0], r[1], r[2], r[3]
        starts_at_str = (rules_json or {}).get("scoring_starts_at")
        if not starts_at_str:
            continue

        try:
            starts_at = datetime.fromisoformat(starts_at_str)
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.warning(
                "golf_pool_bad_scoring_starts_at",
                pool_id=pool_id,
                value=starts_at_str,
            )
            continue

        if now >= starts_at:
            session.execute(
                text("""
                    UPDATE golf_pools
                    SET status = 'live', scoring_enabled = TRUE, updated_at = NOW()
                    WHERE id = :id
                """),
                {"id": pool_id},
            )
            events.append({
                "pool_id": pool_id,
                "code": code,
                "action": "auto_activated",
                "from_status": old_status,
                "scoring_starts_at": starts_at_str,
            })
            logger.info(
                "golf_pool_auto_activated",
                pool_id=pool_id,
                code=code,
                from_status=old_status,
                scoring_starts_at=starts_at_str,
            )

    if events:
        session.commit()

    return events


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def _load_live_pools(session: Session) -> list[dict[str, Any]]:
    """Load all pools with status='live' and scoring_enabled=True."""
    rows = session.execute(
        text("""
            SELECT id, club_code, tournament_id, rules_json, status
            FROM golf_pools
            WHERE status = 'live' AND scoring_enabled = TRUE
        """)
    ).fetchall()

    return [
        {
            "id": r[0],
            "club_code": r[1],
            "tournament_id": r[2],
            "rules_json": r[3],
            "status": r[4],
        }
        for r in rows
    ]


def _load_entries_and_picks(session: Session, pool_id: int) -> list[dict[str, Any]]:
    """Load all entries and their picks for a pool."""
    entry_rows = session.execute(
        text("""
            SELECT id, email, entry_name
            FROM golf_pool_entries
            WHERE pool_id = :pool_id
        """),
        {"pool_id": pool_id},
    ).fetchall()

    entries = []
    for er in entry_rows:
        entry_id = er[0]
        pick_rows = session.execute(
            text("""
                SELECT dg_id, player_name_snapshot, pick_slot, bucket_number
                FROM golf_pool_entry_picks
                WHERE entry_id = :entry_id
                ORDER BY pick_slot
            """),
            {"entry_id": entry_id},
        ).fetchall()

        picks = [
            {
                "dg_id": pr[0],
                "player_name": pr[1],
                "pick_slot": pr[2],
                "bucket_number": pr[3],
            }
            for pr in pick_rows
        ]

        entries.append({
            "entry_id": entry_id,
            "email": er[1],
            "entry_name": er[2],
            "picks": picks,
        })

    return entries


def _load_leaderboard(session: Session, tournament_id: int) -> dict[int, dict[str, Any]]:
    """Load leaderboard data keyed by dg_id."""
    rows = session.execute(
        text("""
            SELECT dg_id, player_name, status, position, total_score,
                   thru, r1, r2, r3, r4
            FROM golf_leaderboard
            WHERE tournament_id = :tournament_id
        """),
        {"tournament_id": tournament_id},
    ).fetchall()

    return {
        r[0]: {
            "dg_id": r[0],
            "player_name": r[1],
            "status": r[2],
            "position": r[3],
            "total_score": r[4],
            "thru": r[5],
            "r1": r[6],
            "r2": r[7],
            "r3": r[8],
            "r4": r[9],
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# Pure scoring logic (lightweight port from api scoring engine)
# ---------------------------------------------------------------------------

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

def _upsert_entry_score(session: Session, pool_id: int, scored: dict[str, Any]) -> None:
    """Upsert a single materialized entry score row.

    Unique constraint: ``entry_id`` (not ``pool_id, entry_id``).
    """
    session.execute(
        text("""
            INSERT INTO golf_pool_entry_scores
                (pool_id, entry_id, rank, is_tied, aggregate_score,
                 qualified_golfers_count, counted_golfers_count,
                 qualification_status, is_complete, last_scored_at,
                 updated_at)
            VALUES
                (:pool_id, :entry_id, :rank, :is_tied, :aggregate_score,
                 :qualified_golfers_count, :counted_golfers_count,
                 :qualification_status, :is_complete, NOW(), NOW())
            ON CONFLICT (entry_id) DO UPDATE SET
                pool_id                 = EXCLUDED.pool_id,
                rank                    = EXCLUDED.rank,
                is_tied                 = EXCLUDED.is_tied,
                aggregate_score         = EXCLUDED.aggregate_score,
                qualified_golfers_count = EXCLUDED.qualified_golfers_count,
                counted_golfers_count   = EXCLUDED.counted_golfers_count,
                qualification_status    = EXCLUDED.qualification_status,
                is_complete             = EXCLUDED.is_complete,
                last_scored_at          = NOW(),
                updated_at              = NOW()
        """),
        {
            "pool_id": pool_id,
            "entry_id": scored["entry_id"],
            "rank": scored["rank"],
            "is_tied": scored["is_tied"],
            "aggregate_score": scored["aggregate_score"],
            "qualified_golfers_count": scored["qualified_golfers_count"],
            "counted_golfers_count": scored["counted_golfers_count"],
            "qualification_status": scored["qualification_status"],
            "is_complete": scored["is_complete"],
        },
    )


def _upsert_score_players(
    session: Session,
    pool_id: int,
    entry_id: int,
    picks: list[dict[str, Any]],
) -> None:
    """Upsert per-golfer score detail rows.

    Column names use ``_snapshot`` suffix where the migration defines them:
    ``player_name_snapshot``, ``status_snapshot``, ``position_snapshot``,
    ``thru_snapshot``, ``total_score_snapshot``, ``made_cut_snapshot``.
    Round columns ``r1``-``r4`` have no suffix.

    Unique constraint: ``(entry_id, dg_id)``
    """
    for pick in picks:
        session.execute(
            text("""
                INSERT INTO golf_pool_entry_score_players
                    (pool_id, entry_id, dg_id, player_name_snapshot, pick_slot,
                     bucket_number, status_snapshot, position_snapshot,
                     total_score_snapshot, thru_snapshot,
                     r1, r2, r3, r4,
                     made_cut_snapshot, counts_toward_total, is_dropped,
                     sort_score, last_scored_at, updated_at)
                VALUES
                    (:pool_id, :entry_id, :dg_id, :player_name, :pick_slot,
                     :bucket_number, :status, :position,
                     :total_score, :thru,
                     :r1, :r2, :r3, :r4,
                     :made_cut, :counts_toward_total, :is_dropped,
                     :sort_score, NOW(), NOW())
                ON CONFLICT (entry_id, dg_id) DO UPDATE SET
                    pool_id                 = EXCLUDED.pool_id,
                    player_name_snapshot    = EXCLUDED.player_name_snapshot,
                    pick_slot               = EXCLUDED.pick_slot,
                    bucket_number           = EXCLUDED.bucket_number,
                    status_snapshot         = EXCLUDED.status_snapshot,
                    position_snapshot       = EXCLUDED.position_snapshot,
                    total_score_snapshot    = EXCLUDED.total_score_snapshot,
                    thru_snapshot           = EXCLUDED.thru_snapshot,
                    r1                      = EXCLUDED.r1,
                    r2                      = EXCLUDED.r2,
                    r3                      = EXCLUDED.r3,
                    r4                      = EXCLUDED.r4,
                    made_cut_snapshot       = EXCLUDED.made_cut_snapshot,
                    counts_toward_total     = EXCLUDED.counts_toward_total,
                    is_dropped              = EXCLUDED.is_dropped,
                    sort_score              = EXCLUDED.sort_score,
                    last_scored_at          = NOW(),
                    updated_at              = NOW()
            """),
            {
                "pool_id": pool_id,
                "entry_id": entry_id,
                "dg_id": pick["dg_id"],
                "player_name": pick["player_name"],
                "pick_slot": pick["pick_slot"],
                "bucket_number": pick.get("bucket_number"),
                "status": pick["status"],
                "position": pick.get("position"),
                "total_score": pick.get("total_score"),
                "thru": pick.get("thru"),
                "r1": pick.get("r1"),
                "r2": pick.get("r2"),
                "r3": pick.get("r3"),
                "r4": pick.get("r4"),
                "made_cut": pick["made_cut"],
                "counts_toward_total": pick["counts_toward_total"],
                "is_dropped": pick["is_dropped"],
                "sort_score": pick.get("sort_score"),
            },
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_all_live_pools(session: Session) -> dict[str, Any]:
    """Score all live pools and write materialized results.

    Also handles auto-activation: pools whose ``scoring_starts_at``
    (in ``rules_json``) has passed are transitioned to live and scored
    in the same tick.

    Returns summary dict suitable for Celery task result.
    """
    # Auto-lock/activate pools whose time has come
    activation_events = _auto_activate_pools(session)

    pools = _load_live_pools(session)

    if not pools:
        logger.info("golf_pool_scoring_no_live_pools")
        return {"pools_scored": 0, "total_entries": 0}

    total_entries = 0
    pools_scored = 0

    for pool in pools:
        pool_id = pool["id"]
        tournament_id = pool["tournament_id"]

        try:
            entries = _load_entries_and_picks(session, pool_id)
            if not entries:
                logger.debug("golf_pool_scoring_no_entries", pool_id=pool_id)
                continue

            leaderboard = _load_leaderboard(session, tournament_id)
            if not leaderboard:
                logger.debug("golf_pool_scoring_no_leaderboard", pool_id=pool_id, tournament_id=tournament_id)
                continue

            rules = _parse_rules(pool.get("rules_json"))

            scored_entries = [_score_entry(e, leaderboard, rules) for e in entries]
            ranked = _rank_entries(scored_entries)

            for scored in ranked:
                _upsert_entry_score(session, pool_id, scored)
                _upsert_score_players(session, pool_id, scored["entry_id"], scored["picks"])

            session.commit()

            total_entries += len(ranked)
            pools_scored += 1

            logger.info(
                "golf_pool_scored",
                pool_id=pool_id,
                club_code=pool["club_code"],
                entries=len(ranked),
            )

        except Exception as exc:
            session.rollback()
            logger.exception(
                "golf_pool_scoring_failed",
                pool_id=pool_id,
                error=str(exc),
            )

    result: dict[str, Any] = {"pools_scored": pools_scored, "total_entries": total_entries}
    if activation_events:
        result["activations"] = activation_events
    return result
