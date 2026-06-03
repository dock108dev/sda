"""Game detail and preview-score endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...db import AsyncSession, get_db
from ...db.flow import SportsGameFlow
from ...db.mlb_advanced import (
    MLBGameAdvancedStats,
    MLBPitcherGameStats,
    MLBPlayerAdvancedStats,
    MLBPlayerFieldingStats,
)
from ...db.nba_advanced import (
    NBAGameAdvancedStats,
    NBAPlayerAdvancedStats,
)
from ...db.ncaab_advanced import (
    NCAABGameAdvancedStats,
    NCAABPlayerAdvancedStats,
)
from ...db.nfl_advanced import (
    NFLGameAdvancedStats,
    NFLPlayerAdvancedStats,
)
from ...db.nhl_advanced import (
    NHLGameAdvancedStats,
    NHLGoalieAdvancedStats,
    NHLSkaterAdvancedStats,
)
from ...db.social import TeamSocialPost
from ...db.sports import (
    SportsGame,
    SportsGamePlay,
    SportsPlayerBoxscore,
    SportsTeamBoxscore,
)
from ...feed.debug_schemas import CardGenerationDebugResponse
from ...services.derived_metrics import compute_derived_metrics
from ...services.game_status import compute_status_flags
from ...services.odds_table import build_odds_table
from ...services.period_labels import period_label, time_label
from ...services.play_importance import (
    DetailContractError,
    enrich_play_importance,
    validate_detail_contract,
)
from ...services.play_tiers import classify_all_tiers, enrich_play_entries, group_tier3_plays
from ...services.stat_annotations import compute_team_annotations
from ...services.team_colors import get_matchup_colors
from .common import (
    serialize_mlb_batter,
    serialize_mlb_pitcher,
    serialize_nhl_goalie,
    serialize_nhl_skater,
    serialize_play_entry,
    serialize_player_stat,
    serialize_team_stat,
)
from .game_detail_advanced import (
    serialize_mlb_advanced,
    serialize_nba_advanced,
    serialize_ncaab_advanced,
    serialize_nfl_advanced,
    serialize_nhl_advanced,
)
from .game_helpers import (
    serialize_social_posts,
)
from .game_preview import router as preview_router
from .nhl_helpers import compute_nhl_data_health
from .schemas import (
    GameDetailResponse,
    GameMeta,
    LiveSnapshot,
    MLBBatterStat,
    MLBPitcherStat,
    NHLGoalieStat,
    NHLSkaterStat,
    OddsEntry,
)
from .schemas.common import _score_obj

router = APIRouter()
logger = logging.getLogger(__name__)


router.include_router(preview_router)


@router.get(
    "/games/{game_id}/card-generation-debug",
    response_model=CardGenerationDebugResponse,
    response_model_by_alias=True,
)
async def get_game_card_generation_debug(
    game_id: int,
    through_play_index: int | None = Query(None, ge=0, alias="throughPlayIndex"),
    include_feed: bool = Query(True, alias="includeFeed"),
    session: AsyncSession = Depends(get_db),
) -> CardGenerationDebugResponse:
    """Admin-only view of cross-sport narrative card generation state."""
    from ...feed.service import build_card_generation_debug_from_game, card_feed_game_options

    result = await session.execute(
        select(SportsGame)
        .options(*card_feed_game_options())
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game Data Not Found",
        )
    return build_card_generation_debug_from_game(
        game,
        through_play_index=through_play_index,
        include_feed=include_feed,
    )


@router.get("/games/{game_id}/admin-detail", response_model=GameDetailResponse)
async def get_game(game_id: int, session: AsyncSession = Depends(get_db)) -> GameDetailResponse:
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
            selectinload(SportsGame.team_boxscores).selectinload(SportsTeamBoxscore.team),
            selectinload(SportsGame.player_boxscores).selectinload(SportsPlayerBoxscore.team),
            selectinload(SportsGame.odds),
            selectinload(SportsGame.social_posts).selectinload(TeamSocialPost.team),
            selectinload(SportsGame.plays).selectinload(SportsGamePlay.team),
            selectinload(SportsGame.timeline_artifacts),
            selectinload(SportsGame.advanced_stats).selectinload(MLBGameAdvancedStats.team),
            selectinload(SportsGame.player_advanced_stats).selectinload(
                MLBPlayerAdvancedStats.team
            ),
            selectinload(SportsGame.pitcher_game_stats).selectinload(
                MLBPitcherGameStats.team
            ),
            selectinload(SportsGame.fielding_stats).selectinload(
                MLBPlayerFieldingStats.team
            ),
            selectinload(SportsGame.nba_advanced_stats).selectinload(
                NBAGameAdvancedStats.team
            ),
            selectinload(SportsGame.nba_player_advanced_stats).selectinload(
                NBAPlayerAdvancedStats.team
            ),
            selectinload(SportsGame.nhl_advanced_stats).selectinload(
                NHLGameAdvancedStats.team
            ),
            selectinload(SportsGame.nhl_skater_advanced_stats).selectinload(
                NHLSkaterAdvancedStats.team
            ),
            selectinload(SportsGame.nhl_goalie_advanced_stats).selectinload(
                NHLGoalieAdvancedStats.team
            ),
            selectinload(SportsGame.nfl_advanced_stats).selectinload(
                NFLGameAdvancedStats.team
            ),
            selectinload(SportsGame.nfl_player_advanced_stats).selectinload(
                NFLPlayerAdvancedStats.team
            ),
            selectinload(SportsGame.ncaab_advanced_stats).selectinload(
                NCAABGameAdvancedStats.team
            ),
            selectinload(SportsGame.ncaab_player_advanced_stats).selectinload(
                NCAABPlayerAdvancedStats.team
            ),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

    # Determine league
    league_code = game.league.code if game.league else None
    is_nhl = league_code == "NHL"
    is_mlb = league_code == "MLB"

    team_stats = [serialize_team_stat(box, league_code=league_code) for box in game.team_boxscores]

    # For NHL/MLB, separate into sport-specific lists; for other sports use generic player stats
    nhl_skaters: list[NHLSkaterStat] | None = None
    nhl_goalies: list[NHLGoalieStat] | None = None
    mlb_batters: list[MLBBatterStat] | None = None
    mlb_pitchers: list[MLBPitcherStat] | None = None
    player_stats: list = []

    if is_nhl:
        # NHL: populate sport-specific lists sorted by TOI desc, leave player_stats empty
        skaters = []
        goalies = []
        for player in game.player_boxscores:
            stats = player.stats or {}
            player_role = stats.get("player_role")
            if player_role == "goalie":
                goalies.append(serialize_nhl_goalie(player))
            else:
                skaters.append(serialize_nhl_skater(player))

        def _toi_sort_key(p) -> float:
            """Extract TOI as minutes for sorting (higher = first)."""
            toi = getattr(p, "toi", None)
            if isinstance(toi, str) and ":" in toi:
                parts = toi.split(":")
                return int(parts[0]) + int(parts[1]) / 60
            return 0.0

        nhl_skaters = sorted(skaters, key=_toi_sort_key, reverse=True)
        nhl_goalies = sorted(goalies, key=_toi_sort_key, reverse=True)
    elif is_mlb:
        # MLB: separate batters and pitchers, leave player_stats empty
        batters = []
        pitchers = []
        for player in game.player_boxscores:
            stats = player.stats or {}
            player_role = stats.get("player_role")
            if player_role == "pitcher":
                pitchers.append(serialize_mlb_pitcher(player))
            else:
                batters.append(serialize_mlb_batter(player))
        mlb_batters = batters
        mlb_pitchers = pitchers
    else:
        # Non-NHL/MLB: use generic player stats
        player_stats = [
            serialize_player_stat(player, league_code=league_code)
            for player in game.player_boxscores
        ]

    odds_entries = [
        OddsEntry(
            book=odd.book,
            market_type=odd.market_type,
            market_category=odd.market_category,
            player_name=odd.player_name,
            description=odd.description,
            side=odd.side,
            line=odd.line,
            price=odd.price,
            is_closing_line=odd.is_closing_line,
            observed_at=odd.observed_at,
        )
        for odd in game.odds
    ]

    plays_entries = [
        serialize_play_entry(play, league_code)
        for play in sorted(game.plays, key=lambda p: p.play_index)
    ]
    if not plays_entries:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game Detail Not Found",
        )

    home_abbr_val = game.home_team.abbreviation if game.home_team else None
    away_abbr_val = game.away_team.abbreviation if game.away_team else None

    # Classify play tiers and build grouped plays
    if league_code:
        tiers = classify_all_tiers(plays_entries, league_code)
        for entry, t in zip(plays_entries, tiers, strict=False):
            entry.tier = t
        grouped_plays = group_tier3_plays(plays_entries, tiers)
        if home_abbr_val and away_abbr_val:
            try:
                enrich_play_entries(plays_entries, league_code, home_abbr_val, away_abbr_val)
                enrich_play_importance(
                    plays_entries,
                    league_code=league_code,
                    home_abbr=home_abbr_val,
                    away_abbr=away_abbr_val,
                )
                validate_detail_contract(plays_entries)
            except DetailContractError as exc:
                logger.warning("Incomplete game detail contract for game %s: %s", game_id, exc)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Game Detail Incomplete",
                ) from exc
            except Exception as exc:
                logger.exception("Detail enrichment failed for game %s", game_id)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Detail Enrichment Failed",
                ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Game Detail Incomplete",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Game Detail Incomplete",
        )

    # Check if game has a flow in SportsGameFlow table
    flow_check = await session.execute(
        select(SportsGameFlow.id)
        .where(
            SportsGameFlow.game_id == game_id,
            SportsGameFlow.moments_json.isnot(None),
        )
        .limit(1)
    )
    has_flow = flow_check.scalar() is not None

    matchup_colors = get_matchup_colors(
        game.home_team.color_light_hex if game.home_team else None,
        game.home_team.color_dark_hex if game.home_team else None,
        game.away_team.color_light_hex if game.away_team else None,
        game.away_team.color_dark_hex if game.away_team else None,
        away_secondary_light=game.away_team.color_secondary_light_hex if game.away_team else None,
        away_secondary_dark=game.away_team.color_secondary_dark_hex if game.away_team else None,
    )

    status_flags = compute_status_flags(game.status)
    latest_play = max(game.plays, key=lambda p: p.play_index, default=None) if game.plays else None
    meta_current_period = getattr(latest_play, "quarter", None) if latest_play else None
    meta_game_clock = getattr(latest_play, "game_clock", None) if latest_play else None

    meta_period_label: str | None = None
    meta_live_snapshot: LiveSnapshot | None = None
    if meta_current_period is not None and league_code:
        meta_period_label = period_label(meta_current_period, league_code)
        meta_live_snapshot = LiveSnapshot(
            period_label=meta_period_label,
            time_label=time_label(meta_current_period, meta_game_clock, league_code),
            score=_score_obj(game.home_score, game.away_score),
            current_period=meta_current_period,
            game_clock=meta_game_clock,
        )

    meta = GameMeta(
        id=game.id,
        league_code=game.league.code if game.league else "UNKNOWN",
        season=game.season,
        season_type=getattr(game, "season_type", None),
        game_date=game.game_date,
        local_game_date=getattr(game, "local_game_date", None),
        home_team=game.home_team.name if game.home_team else "Unknown",
        away_team=game.away_team.name if game.away_team else "Unknown",
        home_team_id=game.home_team.id if game.home_team else None,
        away_team_id=game.away_team.id if game.away_team else None,
        score=_score_obj(game.home_score, game.away_score),
        status=game.status,
        scrape_version=getattr(game, "scrape_version", None),
        last_scraped_at=game.last_scraped_at,
        last_ingested_at=game.last_ingested_at,
        last_pbp_at=game.last_pbp_at,
        last_social_at=game.last_social_at,
        last_odds_at=game.last_odds_at,
        last_advanced_stats_at=getattr(game, "last_advanced_stats_at", None),
        has_boxscore=bool(game.team_boxscores),
        has_player_stats=bool(game.player_boxscores),
        has_odds=bool(game.odds),
        has_social=bool(game.social_posts),
        has_pbp=bool(game.plays),
        has_flow=has_flow,
        has_advanced_stats=getattr(game, "last_advanced_stats_at", None) is not None,
        play_count=len(game.plays) if game.plays else 0,
        social_post_count=len(game.social_posts) if game.social_posts else 0,
        home_team_x_handle=game.home_team.x_handle if game.home_team else None,
        away_team_x_handle=game.away_team.x_handle if game.away_team else None,
        homeTeamAbbr=game.home_team.abbreviation if game.home_team else None,
        awayTeamAbbr=game.away_team.abbreviation if game.away_team else None,
        homeTeamColorLight=matchup_colors["homeLightHex"],
        homeTeamColorDark=matchup_colors["homeDarkHex"],
        awayTeamColorLight=matchup_colors["awayLightHex"],
        awayTeamColorDark=matchup_colors["awayDarkHex"],
        is_truly_completed=status_flags["is_truly_completed"],
        read_eligible=status_flags["read_eligible"],
        current_period_label=meta_period_label,
        live_snapshot=meta_live_snapshot,
    )

    social_posts_entries = serialize_social_posts(game, game.social_posts or [])

    derived = compute_derived_metrics(game, game.odds)
    raw_payloads = {
        "team_boxscores": [
            {
                "team": box.team.name if box.team else "Unknown",
                "stats": box.stats,
                "source": box.source,
            }
            for box in game.team_boxscores
            if box.stats
        ],
        "player_boxscores": [
            {
                "team": player.team.name if player.team else "Unknown",
                "player": player.player_name,
                "stats": player.stats,
            }
            for player in game.player_boxscores
            if player.stats
        ],
        "odds": [
            {
                "book": odd.book,
                "market_type": odd.market_type,
                "raw": odd.raw_payload,
            }
            for odd in game.odds
            if odd.raw_payload
        ],
    }

    # Compute NHL-specific data health (None for non-NHL games)
    data_health = compute_nhl_data_health(game, game.player_boxscores)

    odds_table = build_odds_table(game.odds) if game.odds else None

    stat_annotations: list[dict] | None = None
    home_box = next((b for b in game.team_boxscores if b.is_home), None)
    away_box = next((b for b in game.team_boxscores if not b.is_home), None)
    if home_box and away_box and league_code:
        home_abbr = game.home_team.abbreviation if game.home_team else None
        away_abbr = game.away_team.abbreviation if game.away_team else None
        if home_abbr and away_abbr:
            stat_annotations = compute_team_annotations(
                home_box.stats or {},
                away_box.stats or {},
                home_abbr,
                away_abbr,
                league_code,
            )

    # Advanced stats serialization (delegated to game_detail_advanced module)
    is_nba = league_code == "NBA"
    is_nfl = league_code == "NFL"
    is_ncaab = league_code == "NCAAB"

    mlb_advanced_stats_list, mlb_advanced_player_stats_list, mlb_pitcher_game_stats_list, mlb_fielding_stats_list = serialize_mlb_advanced(game) if is_mlb else (None, None, None, None)
    nba_advanced_stats_list, nba_player_advanced_stats_list = serialize_nba_advanced(game) if is_nba else (None, None)
    nhl_advanced_stats_list, nhl_skater_advanced_stats_list, nhl_goalie_advanced_stats_list = serialize_nhl_advanced(game) if is_nhl else (None, None, None)
    nfl_advanced_stats_list, nfl_player_advanced_stats_list = serialize_nfl_advanced(game) if is_nfl else (None, None)
    ncaab_advanced_stats_list, ncaab_player_advanced_stats_list = serialize_ncaab_advanced(game) if is_ncaab else (None, None)

    return GameDetailResponse(
        game=meta,
        team_stats=team_stats,
        player_stats=player_stats,
        nhl_skaters=nhl_skaters,
        nhl_goalies=nhl_goalies,
        mlb_batters=mlb_batters,
        mlb_pitchers=mlb_pitchers,
        mlb_advanced_stats=mlb_advanced_stats_list,
        mlb_advanced_player_stats=mlb_advanced_player_stats_list,
        mlb_pitcher_game_stats=mlb_pitcher_game_stats_list,
        mlb_fielding_stats=mlb_fielding_stats_list,
        nba_advanced_stats=nba_advanced_stats_list,
        nba_player_advanced_stats=nba_player_advanced_stats_list,
        nhl_advanced_stats=nhl_advanced_stats_list,
        nhl_skater_advanced_stats=nhl_skater_advanced_stats_list,
        nhl_goalie_advanced_stats=nhl_goalie_advanced_stats_list,
        nfl_advanced_stats=nfl_advanced_stats_list,
        nfl_player_advanced_stats=nfl_player_advanced_stats_list,
        ncaab_advanced_stats=ncaab_advanced_stats_list,
        ncaab_player_advanced_stats=ncaab_player_advanced_stats_list,
        odds=odds_entries,
        social_posts=social_posts_entries,
        plays=plays_entries,
        grouped_plays=grouped_plays,
        derived_metrics=derived,
        raw_payloads=raw_payloads,
        data_health=data_health,
        odds_table=odds_table,
        stat_annotations=stat_annotations,
    )
