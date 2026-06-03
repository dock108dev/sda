"""Golf pool scoring public entry points."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from ..logging import logger
from .pool_engine import _parse_rules, _rank_entries, _score_entry
from .pool_lifecycle import _auto_activate_pools
from .pool_loaders import _load_entries_and_picks, _load_leaderboard, _load_live_pools
from .pool_persistence import _upsert_entry_score, _upsert_score_players

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


def score_single_pool(session: Session, pool_id: int) -> dict[str, Any]:
    """Score a single pool by ID, regardless of status/scoring_enabled.

    Used by the manual rescore admin action.
    """
    row = session.execute(
        text("""
            SELECT id, club_code, tournament_id, rules_json, status
            FROM golf_pools
            WHERE id = :pool_id
        """),
        {"pool_id": pool_id},
    ).fetchone()

    if not row:
        logger.warning("golf_pool_rescore_not_found", pool_id=pool_id)
        return {"error": "pool_not_found", "pool_id": pool_id}

    pool = {
        "id": row[0],
        "club_code": row[1],
        "tournament_id": row[2],
        "rules_json": row[3],
        "status": row[4],
    }

    entries = _load_entries_and_picks(session, pool_id)
    if not entries:
        logger.info("golf_pool_rescore_no_entries", pool_id=pool_id)
        return {"pool_id": pool_id, "entries_scored": 0, "reason": "no_entries"}

    leaderboard = _load_leaderboard(session, pool["tournament_id"])
    if not leaderboard:
        logger.info(
            "golf_pool_rescore_no_leaderboard",
            pool_id=pool_id,
            tournament_id=pool["tournament_id"],
        )
        return {"pool_id": pool_id, "entries_scored": 0, "reason": "no_leaderboard"}

    rules = _parse_rules(pool.get("rules_json"))
    scored_entries = [_score_entry(e, leaderboard, rules) for e in entries]
    ranked = _rank_entries(scored_entries)

    for scored in ranked:
        _upsert_entry_score(session, pool_id, scored)
        _upsert_score_players(session, pool_id, scored["entry_id"], scored["picks"])

    session.commit()

    logger.info(
        "golf_pool_rescored",
        pool_id=pool_id,
        club_code=pool["club_code"],
        entries=len(ranked),
    )
    return {"pool_id": pool_id, "entries_scored": len(ranked)}
