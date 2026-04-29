"""Fetch probable lineups for upcoming MLB games.

For scheduled/pregame games where PBP doesn't exist yet:

- **Probable pitcher:** Fetched from the MLB Stats API schedule endpoint
  which publishes probable starters typically 1-2 days before game time.
- **Batting order:** Uses the team's most recent actual lineup
  reconstructed from their last completed game's PBP.  MLB teams
  typically run similar lineups game to game, making this a reasonable
  proxy.
- **Consensus lineup:** Analyses the last N games to find the most
  frequent 9 starters and their typical batting order positions,
  producing a more stable prediction than a single game.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def fetch_probable_starter(
    game_date: date,
    team_external_ref: str,
) -> dict[str, str] | None:
    """Fetch the probable starting pitcher from the MLB Stats API.

    The schedule endpoint ``/api/v1/schedule`` with
    ``hydrate=probablePitcher`` returns announced starters for each game.

    Args:
        game_date: Date of the game.
        team_external_ref: MLB Stats API team ID (e.g., ``"147"``).

    Returns:
        ``{"external_ref": str, "name": str}`` or ``None`` if not
        announced or API unavailable.
    """
    import httpx

    date_str = game_date.isoformat()
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?date={date_str}&sportId=1&hydrate=probablePitcher"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.warning(
            "probable_pitcher_api_failed",
            extra={"date": date_str, "team_ref": team_external_ref},
        )
        return None

    for game_date_entry in data.get("dates", []):
        for game in game_date_entry.get("games", []):
            # Check if this team is home or away
            teams = game.get("teams", {})
            for side in ("home", "away"):
                team_data = teams.get(side, {})
                team_info = team_data.get("team", {})
                if str(team_info.get("id", "")) == str(team_external_ref):
                    pitcher = team_data.get("probablePitcher", {})
                    pitcher_id = str(pitcher.get("id", ""))
                    pitcher_name = pitcher.get("fullName", "")
                    if pitcher_id:
                        return {
                            "external_ref": pitcher_id,
                            "name": pitcher_name,
                        }
    return None


async def fetch_recent_lineup(
    db: AsyncSession,
    team_id: int,
    before_game_id: int | None = None,
) -> list[dict[str, str]] | None:
    """Get the team's most recent batting order from PBP.

    Looks at the team's last completed game and reconstructs the
    starting lineup from play-by-play data.

    Args:
        db: Async database session.
        team_id: Team ID.
        before_game_id: If provided, only consider games before this one
            (prevents using the same game we're simulating).

    Returns:
        List of ``{"external_ref": str, "name": str}`` in batting order,
        or ``None`` if no recent PBP data found.
    """
    from app.db.sports import SportsGame

    # Find the team's most recent final game with PBP
    stmt = (
        select(SportsGame.id)
        .where(
            SportsGame.status.in_(["final", "archived"]),
            (SportsGame.home_team_id == team_id) | (SportsGame.away_team_id == team_id),
        )
        .order_by(SportsGame.game_date.desc())
        .limit(1)
    )
    if before_game_id is not None:
        stmt = stmt.where(SportsGame.id != before_game_id)

    result = await db.execute(stmt)
    recent_game_id = result.scalar_one_or_none()

    if recent_game_id is None:
        return None

    from app.analytics.services.lineup_reconstruction import (
        reconstruct_lineup_from_pbp,
    )

    lineup_data = await reconstruct_lineup_from_pbp(db, recent_game_id, team_id)
    if lineup_data is None:
        return None

    return lineup_data["batters"]


async def fetch_consensus_lineup(
    db: AsyncSession,
    team_id: int,
    before_game_id: int | None = None,
    num_games: int = 7,
) -> list[dict[str, str]] | None:
    """Build a consensus batting order from the last ``num_games`` lineups.

    Instead of using a single game's lineup (which can be thrown off by
    rest days, platoon swaps, or pinch-hit substitutions), this analyses
    multiple recent games to identify the most frequent 9 starters and
    their typical batting order positions.

    Algorithm:
        1. Reconstruct lineups from the last ``num_games`` completed games.
        2. Count per-player appearances across all lineups (frequency).
        3. Take the top 9 players by frequency as consensus starters.
        4. For each starter, find their most common batting order position
           (mode).  Tiebreaker: most recent game wins.
        5. Resolve slot conflicts (two players sharing a mode position)
           by giving the slot to the player with more appearances there.

    Falls back to :func:`fetch_recent_lineup` if fewer than 3 games
    have reconstructable lineups.

    Args:
        db: Async database session.
        team_id: Team ID.
        before_game_id: Exclude this game (prevents using the game
            we're simulating).
        num_games: Number of recent games to analyse (default 7).

    Returns:
        List of ``{"external_ref": str, "name": str}`` in batting order,
        or ``None`` if insufficient data.
    """
    from collections import Counter, defaultdict

    from app.analytics.services.lineup_reconstruction import (
        reconstruct_lineup_from_pbp,
    )
    from app.db.sports import SportsGame

    # Find the last num_games completed games for this team
    stmt = (
        select(SportsGame.id)
        .where(
            SportsGame.status.in_(["final", "archived"]),
            (SportsGame.home_team_id == team_id)
            | (SportsGame.away_team_id == team_id),
        )
        .order_by(SportsGame.game_date.desc())
        .limit(num_games)
    )
    if before_game_id is not None:
        stmt = stmt.where(SportsGame.id != before_game_id)

    result = await db.execute(stmt)
    game_ids = result.scalars().all()

    if not game_ids:
        return None

    # Reconstruct each lineup
    all_lineups: list[list[dict[str, str]]] = []
    for gid in game_ids:
        lineup_data = await reconstruct_lineup_from_pbp(db, gid, team_id)
        if lineup_data and lineup_data.get("batters"):
            all_lineups.append(lineup_data["batters"])

    if len(all_lineups) < 3:
        logger.info(
            "consensus_lineup_fallback_to_recent",
            extra={
                "team_id": team_id,
                "lineups_found": len(all_lineups),
                "games_checked": len(game_ids),
            },
        )
        return await fetch_recent_lineup(db, team_id, before_game_id)

    # Count appearances per player
    appearance_count: Counter[str] = Counter()
    player_names: dict[str, str] = {}
    # Track which batting order positions each player has occupied
    # position_history[external_ref] = [(position_index, recency), ...]
    position_history: dict[str, list[tuple[int, int]]] = defaultdict(list)

    for game_idx, lineup in enumerate(all_lineups):
        recency = len(all_lineups) - game_idx  # higher = more recent
        for pos_idx, batter in enumerate(lineup):
            ref = batter["external_ref"]
            appearance_count[ref] += 1
            player_names[ref] = batter["name"]
            position_history[ref].append((pos_idx, recency))

    # Top 9 by frequency
    top_9_refs = [ref for ref, _ in appearance_count.most_common(9)]

    if len(top_9_refs) < 9:
        # Not enough unique players — use what we have
        pass

    # For each player, find their most common position (mode)
    # Tiebreaker: prefer the position from the most recent game
    player_best_pos: dict[str, int] = {}
    for ref in top_9_refs:
        positions = position_history[ref]
        pos_counter: Counter[int] = Counter()
        pos_max_recency: dict[int, int] = {}
        for pos, recency in positions:
            pos_counter[pos] += 1
            if pos not in pos_max_recency or recency > pos_max_recency[pos]:
                pos_max_recency[pos] = recency

        # Sort positions by (count desc, recency desc)
        best_pos = max(
            pos_counter.keys(),
            key=lambda p: (pos_counter[p], pos_max_recency.get(p, 0)),
        )
        player_best_pos[ref] = best_pos

    # Resolve slot conflicts: if two players want the same slot,
    # the one with more appearances at that slot wins; the other
    # gets their next-best position.
    assigned_slots: dict[int, str] = {}  # slot -> external_ref
    player_assigned: dict[str, int] = {}  # external_ref -> slot

    # Sort players by total appearances (desc) for priority
    sorted_refs = sorted(top_9_refs, key=lambda r: appearance_count[r], reverse=True)

    for ref in sorted_refs:
        preferred = player_best_pos[ref]
        if preferred not in assigned_slots:
            assigned_slots[preferred] = ref
            player_assigned[ref] = preferred
        else:
            # Slot taken — find next best available position
            positions = position_history[ref]
            pos_counter: Counter[int] = Counter()
            for pos, _ in positions:
                pos_counter[pos] += 1

            # Try positions in order of frequency for this player
            for pos, _ in pos_counter.most_common():
                if pos not in assigned_slots:
                    assigned_slots[pos] = ref
                    player_assigned[ref] = pos
                    break
            else:
                # All preferred positions taken — find any open slot 0-8
                for slot in range(9):
                    if slot not in assigned_slots:
                        assigned_slots[slot] = ref
                        player_assigned[ref] = slot
                        break

    # Build the final lineup in batting order (slot 0 = leadoff, etc.)
    consensus: list[dict[str, str]] = []
    for slot in range(9):
        ref = assigned_slots.get(slot)
        if ref:
            consensus.append({
                "external_ref": ref,
                "name": player_names[ref],
            })

    # If we somehow have gaps, fill with remaining frequent players
    assigned_refs = {b["external_ref"] for b in consensus}
    for ref, _ in appearance_count.most_common():
        if len(consensus) >= 9:
            break
        if ref not in assigned_refs:
            consensus.append({
                "external_ref": ref,
                "name": player_names[ref],
            })

    logger.info(
        "consensus_lineup_built",
        extra={
            "team_id": team_id,
            "games_used": len(all_lineups),
            "consensus_size": len(consensus),
        },
    )

    return consensus[:9] if consensus else None


async def get_team_external_ref(
    db: AsyncSession,
    team_id: int,
) -> str | None:
    """Look up a team's MLB Stats API ID from the DB."""
    from app.db.sports import SportsTeam

    stmt = select(SportsTeam.external_ref).where(SportsTeam.id == team_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
