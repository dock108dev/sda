"""Sport-specific rotation and lineup weight builders for batch simulation.

Each builder attempts to construct per-player or per-unit weights for
a single game.  On success, the weights are injected into ``game_context``
and the function returns a truthy value.  On failure (insufficient data),
it returns a falsey value and the caller falls back to team-level probabilities.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NBA
# ---------------------------------------------------------------------------


async def try_build_nba_rotation_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build starter/bench rotation weights for an NBA game.

    For final games: reconstructs rotation from NBAPlayerAdvancedStats.
    For scheduled/pregame games: uses most recent rotation.

    Returns True if rotation weights were built, False otherwise.
    """
    from app.analytics.services.nba_rotation_service import (
        get_recent_rotation,
        reconstruct_rotation_from_stats,
    )
    from app.analytics.services.nba_rotation_weights import build_rotation_weights

    is_final = game.status in ("final", "archived")

    if is_final:
        home_rotation = await reconstruct_rotation_from_stats(db, game.id, game.home_team_id)
        away_rotation = await reconstruct_rotation_from_stats(db, game.id, game.away_team_id)
    else:
        home_rotation = await get_recent_rotation(db, game.home_team_id, exclude_game_id=game.id)
        away_rotation = await get_recent_rotation(db, game.away_team_id, exclude_game_id=game.id)

    if not home_rotation or not away_rotation:
        return False

    away_def = (away_profile or {}).get("def_rating")
    home_def = (home_profile or {}).get("def_rating")

    home_weights = await build_rotation_weights(
        db, home_rotation, game.home_team_id,
        opposing_def_rating=away_def,
        rolling_window=rolling_window,
    )
    away_weights = await build_rotation_weights(
        db, away_rotation, game.away_team_id,
        opposing_def_rating=home_def,
        rolling_window=rolling_window,
    )

    game_context["home_starter_weights"] = home_weights["starter_weights"]
    game_context["home_bench_weights"] = home_weights["bench_weights"]
    game_context["home_starter_share"] = home_weights["starter_share"]
    game_context["home_ft_pct_starter"] = home_weights["ft_pct_starter"]
    game_context["home_ft_pct_bench"] = home_weights["ft_pct_bench"]

    game_context["away_starter_weights"] = away_weights["starter_weights"]
    game_context["away_bench_weights"] = away_weights["bench_weights"]
    game_context["away_starter_share"] = away_weights["starter_share"]
    game_context["away_ft_pct_starter"] = away_weights["ft_pct_starter"]
    game_context["away_ft_pct_bench"] = away_weights["ft_pct_bench"]

    logger.info(
        "batch_sim_nba_rotation_built",
        extra={
            "game_id": game.id,
            "home_starters": len(home_rotation["starters"]),
            "away_starters": len(away_rotation["starters"]),
            "home_resolved": home_weights["players_resolved"],
            "away_resolved": away_weights["players_resolved"],
            "home_starter_share": home_weights["starter_share"],
            "away_starter_share": away_weights["starter_share"],
        },
    )
    return True


# ---------------------------------------------------------------------------
# NFL
# ---------------------------------------------------------------------------


async def try_build_nfl_drive_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Build drive outcome weights for an NFL game."""
    from app.analytics.services.nfl_drive_weights import build_drive_weights

    result = await build_drive_weights(
        db, game, home_profile, away_profile, rolling_window,
    )

    if result is None:
        return False

    game_context["home_drive_weights"] = result["home_drive_weights"]
    game_context["away_drive_weights"] = result["away_drive_weights"]
    game_context["home_xp_pct"] = result["home_xp_pct"]
    game_context["away_xp_pct"] = result["away_xp_pct"]
    game_context["home_fg_pct"] = result["home_fg_pct"]
    game_context["away_fg_pct"] = result["away_fg_pct"]

    logger.info(
        "batch_sim_nfl_drive_weights_built",
        extra={"game_id": game.id},
    )
    return True


# ---------------------------------------------------------------------------
# NHL
# ---------------------------------------------------------------------------


async def try_build_nhl_rotation_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build top-line/depth rotation weights for an NHL game."""
    from app.analytics.services.nhl_rotation_service import (
        get_recent_rotation,
        reconstruct_rotation_from_stats,
    )
    from app.analytics.services.nhl_rotation_weights import build_rotation_weights

    is_final = game.status in ("final", "archived")

    if is_final:
        home_rotation = await reconstruct_rotation_from_stats(db, game.id, game.home_team_id)
        away_rotation = await reconstruct_rotation_from_stats(db, game.id, game.away_team_id)
    else:
        home_rotation = await get_recent_rotation(db, game.home_team_id, exclude_game_id=game.id)
        away_rotation = await get_recent_rotation(db, game.away_team_id, exclude_game_id=game.id)

    if not home_rotation or not away_rotation:
        return False

    away_goalie = away_rotation.get("goalie", {})
    home_goalie = home_rotation.get("goalie", {})
    away_save_pct = away_goalie.get("save_pct") if away_goalie else None
    home_save_pct = home_goalie.get("save_pct") if home_goalie else None

    home_weights = await build_rotation_weights(
        db, home_rotation, game.home_team_id,
        opposing_goalie_save_pct=away_save_pct,
        rolling_window=rolling_window,
    )
    away_weights = await build_rotation_weights(
        db, away_rotation, game.away_team_id,
        opposing_goalie_save_pct=home_save_pct,
        rolling_window=rolling_window,
    )

    game_context["home_starter_weights"] = home_weights["starter_weights"]
    game_context["home_bench_weights"] = home_weights["bench_weights"]
    game_context["home_starter_share"] = home_weights["starter_share"]

    game_context["away_starter_weights"] = away_weights["starter_weights"]
    game_context["away_bench_weights"] = away_weights["bench_weights"]
    game_context["away_starter_share"] = away_weights["starter_share"]

    logger.info(
        "batch_sim_nhl_rotation_built",
        extra={
            "game_id": game.id,
            "home_resolved": home_weights["players_resolved"],
            "away_resolved": away_weights["players_resolved"],
            "home_goalie": away_goalie.get("name") if away_goalie else None,
            "away_goalie": home_goalie.get("name") if home_goalie else None,
        },
    )
    return True


# ---------------------------------------------------------------------------
# NCAAB
# ---------------------------------------------------------------------------


async def try_build_ncaab_rotation_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> bool:
    """Attempt to build starter/bench rotation weights for an NCAAB game."""
    from app.analytics.services.ncaab_rotation_service import (
        get_recent_rotation,
        reconstruct_rotation_from_stats,
    )
    from app.analytics.services.ncaab_rotation_weights import build_rotation_weights

    is_final = game.status in ("final", "archived")

    if is_final:
        home_rotation = await reconstruct_rotation_from_stats(db, game.id, game.home_team_id)
        away_rotation = await reconstruct_rotation_from_stats(db, game.id, game.away_team_id)
    else:
        home_rotation = await get_recent_rotation(db, game.home_team_id, exclude_game_id=game.id)
        away_rotation = await get_recent_rotation(db, game.away_team_id, exclude_game_id=game.id)

    if not home_rotation or not away_rotation:
        return False

    away_def = (away_profile or {}).get("def_rating")
    home_def = (home_profile or {}).get("def_rating")

    home_weights = await build_rotation_weights(
        db, home_rotation, game.home_team_id,
        opposing_def_rating=away_def,
        rolling_window=rolling_window,
    )
    away_weights = await build_rotation_weights(
        db, away_rotation, game.away_team_id,
        opposing_def_rating=home_def,
        rolling_window=rolling_window,
    )

    game_context["home_starter_weights"] = home_weights["starter_weights"]
    game_context["home_bench_weights"] = home_weights["bench_weights"]
    game_context["home_starter_share"] = home_weights["starter_share"]
    game_context["home_ft_pct_starter"] = home_weights["ft_pct_starter"]
    game_context["home_ft_pct_bench"] = home_weights["ft_pct_bench"]
    game_context["home_orb_pct_starter"] = home_weights["orb_pct_starter"]
    game_context["home_orb_pct_bench"] = home_weights["orb_pct_bench"]

    game_context["away_starter_weights"] = away_weights["starter_weights"]
    game_context["away_bench_weights"] = away_weights["bench_weights"]
    game_context["away_starter_share"] = away_weights["starter_share"]
    game_context["away_ft_pct_starter"] = away_weights["ft_pct_starter"]
    game_context["away_ft_pct_bench"] = away_weights["ft_pct_bench"]
    game_context["away_orb_pct_starter"] = away_weights["orb_pct_starter"]
    game_context["away_orb_pct_bench"] = away_weights["orb_pct_bench"]

    logger.info(
        "batch_sim_ncaab_rotation_built",
        extra={
            "game_id": game.id,
            "home_resolved": home_weights["players_resolved"],
            "away_resolved": away_weights["players_resolved"],
        },
    )
    return True


# ---------------------------------------------------------------------------
# MLB (lineup-aware)
# ---------------------------------------------------------------------------


async def try_build_lineup_weights(
    db: AsyncSession,
    game,
    game_context: dict,
    home_profile: dict | None,
    away_profile: dict | None,
    rolling_window: int,
) -> dict | None:
    """Attempt to build per-batter lineup weights for an MLB game.

    For final games: reconstructs batting order from PBP.
    For scheduled/pregame games: uses consensus lineup + rotation prediction.

    Returns a dict with lineup metadata if weights were built successfully,
    or ``None`` if the caller should fall back to team-level.
    """
    from app.analytics.services.lineup_fetcher import (
        fetch_consensus_lineup,
        get_team_external_ref,
    )
    from app.analytics.services.mlb_rotation_service import (
        predict_probable_starter,
    )
    from app.analytics.services.lineup_reconstruction import (
        get_starting_pitcher,
        reconstruct_lineup_from_pbp,
    )
    from app.analytics.services.lineup_weights import (
        build_lineup_weights,
        pitching_metrics_from_profile,
        regress_pitcher_profile,
    )
    from app.analytics.services.profile_service import get_pitcher_rolling_profile

    fallback_pitcher = {
        "strikeout_rate": 0.22, "walk_rate": 0.08,
        "contact_suppression": 0.0, "power_suppression": 0.0,
    }

    is_final = game.status in ("final", "archived")

    # --- Get lineups ---
    if is_final:
        home_lineup_data = await reconstruct_lineup_from_pbp(
            db, game.id, game.home_team_id,
        )
        away_lineup_data = await reconstruct_lineup_from_pbp(
            db, game.id, game.away_team_id,
        )
    else:
        home_lineup_batters = await fetch_consensus_lineup(
            db, game.home_team_id, before_game_id=game.id,
        )
        away_lineup_batters = await fetch_consensus_lineup(
            db, game.away_team_id, before_game_id=game.id,
        )
        home_lineup_data = {"batters": home_lineup_batters} if home_lineup_batters else None
        away_lineup_data = {"batters": away_lineup_batters} if away_lineup_batters else None

    if not home_lineup_data or not away_lineup_data:
        logger.info(
            "lineup_build_no_lineup_data",
            extra={
                "game_id": game.id,
                "has_home": bool(home_lineup_data),
                "has_away": bool(away_lineup_data),
                "is_final": is_final,
            },
        )
        return None

    home_batters = home_lineup_data["batters"]
    away_batters = away_lineup_data["batters"]

    if len(home_batters) < 3 or len(away_batters) < 3:
        logger.info(
            "lineup_build_insufficient_batters",
            extra={
                "game_id": game.id,
                "home_batters": len(home_batters),
                "away_batters": len(away_batters),
            },
        )
        return None

    # --- Get starting pitchers ---
    away_sp_info: dict | None = None
    home_sp_info: dict | None = None

    if is_final:
        away_sp_info = await get_starting_pitcher(db, game.id, game.away_team_id)
        home_sp_info = await get_starting_pitcher(db, game.id, game.home_team_id)
    else:
        from app.utils.datetime_utils import to_et_date
        game_date = to_et_date(game.game_date) if game.game_date else None
        if game_date:
            away_ext = await get_team_external_ref(db, game.away_team_id)
            home_ext = await get_team_external_ref(db, game.home_team_id)
            away_sp_info = await predict_probable_starter(
                db, game.away_team_id, game_date, away_ext,
            )
            home_sp_info = await predict_probable_starter(
                db, game.home_team_id, game_date, home_ext,
            )

    logger.info(
        "lineup_build_pitcher_lookup",
        extra={
            "game_id": game.id,
            "is_final": is_final,
            "home_sp_found": home_sp_info is not None,
            "away_sp_found": away_sp_info is not None,
            "home_sp_name": (home_sp_info or {}).get("name"),
            "away_sp_name": (away_sp_info or {}).get("name"),
        },
    )

    # --- Get pitcher profiles ---
    away_sp_profile = fallback_pitcher
    home_sp_profile = fallback_pitcher

    if away_sp_info:
        raw = await get_pitcher_rolling_profile(
            away_sp_info["external_ref"], game.away_team_id,
            rolling_window=rolling_window, db=db,
        )
        if raw:
            away_sp_profile = regress_pitcher_profile(raw, away_sp_info.get("avg_ip"))
        else:
            logger.info(
                "lineup_build_pitcher_profile_empty",
                extra={"game_id": game.id, "side": "away", "pitcher_ref": away_sp_info["external_ref"]},
            )

    if home_sp_info:
        raw = await get_pitcher_rolling_profile(
            home_sp_info["external_ref"], game.home_team_id,
            rolling_window=rolling_window, db=db,
        )
        if raw:
            home_sp_profile = regress_pitcher_profile(raw, home_sp_info.get("avg_ip"))
        else:
            logger.info(
                "lineup_build_pitcher_profile_empty",
                extra={"game_id": game.id, "side": "home", "pitcher_ref": home_sp_info["external_ref"]},
            )

    # Bullpen profiles derived from the OPPOSING team's batting tendencies
    away_team_bullpen = pitching_metrics_from_profile(away_profile) or fallback_pitcher
    home_team_bullpen = pitching_metrics_from_profile(home_profile) or fallback_pitcher

    # --- Build per-batter weights ---
    home_weights = await build_lineup_weights(
        db, home_batters, game.home_team_id,
        opposing_starter_profile=away_sp_profile,
        opposing_bullpen_profile=away_team_bullpen,
        team_profile=home_profile,
        rolling_window=rolling_window,
    )
    away_weights = await build_lineup_weights(
        db, away_batters, game.away_team_id,
        opposing_starter_profile=home_sp_profile,
        opposing_bullpen_profile=home_team_bullpen,
        team_profile=away_profile,
        rolling_window=rolling_window,
    )

    game_context["home_lineup_weights"] = home_weights["starter_weights"]
    game_context["away_lineup_weights"] = away_weights["starter_weights"]
    game_context["home_bullpen_weights"] = home_weights["bullpen_weights"]
    game_context["away_bullpen_weights"] = away_weights["bullpen_weights"]
    game_context["starter_innings"] = 6.0

    logger.info(
        "batch_sim_lineup_built",
        extra={
            "game_id": game.id,
            "home_batters": len(home_batters),
            "away_batters": len(away_batters),
            "home_resolved": home_weights["batters_resolved"],
            "away_resolved": away_weights["batters_resolved"],
            "home_sp": home_sp_info.get("name") if home_sp_info else None,
            "away_sp": away_sp_info.get("name") if away_sp_info else None,
        },
    )
    return {
        "home_lineup": home_batters,
        "away_lineup": away_batters,
        "home_starter": home_sp_info,
        "away_starter": away_sp_info,
        "home_weights": home_weights["starter_weights"],
        "away_weights": away_weights["starter_weights"],
    }
