"""Game detail and preview-score endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
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
from ...game_metadata.nuggets import generate_nugget
from ...game_metadata.scoring import excitement_score, quality_score
from ...game_metadata.services import RatingsService, StandingsService
from ...services.derived_metrics import compute_derived_metrics
from ...services.game_status import compute_status_flags
from ...services.odds_table import build_odds_table
from ...services.period_labels import period_label, time_label
from ...services.play_tiers import classify_all_tiers, group_tier3_plays
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
from .game_helpers import (
    build_preview_context,
    normalize_score,
    preview_tags,
    resolve_team_key,
    select_preview_entry,
    serialize_social_posts,
)
from .nhl_helpers import compute_nhl_data_health
from .schemas import (
    GameDetailResponse,
    GameMeta,
    GamePreviewScoreResponse,
    LiveSnapshot,
    MLBAdvancedPlayerStats,
    MLBAdvancedTeamStats,
    MLBBatterStat,
    MLBFieldingStatSchema,
    MLBPitcherGameStatSchema,
    MLBPitcherStat,
    NHLGoalieStat,
    NHLSkaterStat,
    OddsEntry,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/games/{game_id}/preview-score", response_model=GamePreviewScoreResponse)
async def get_game_preview_score(
    game_id: int,
    session: AsyncSession = Depends(get_db),
) -> GamePreviewScoreResponse:
    result = await session.execute(
        select(SportsGame)
        .options(
            selectinload(SportsGame.league),
            selectinload(SportsGame.home_team),
            selectinload(SportsGame.away_team),
        )
        .where(SportsGame.id == game_id)
    )
    game = result.scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
    if not game.home_team or not game.away_team:
        logger.error("Preview score missing team data", extra={"game_id": game_id})
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Game missing team data",
        )

    league_code = game.league.code if game.league else "UNKNOWN"
    ratings_service = RatingsService()
    standings_service = StandingsService()

    try:
        ratings = ratings_service.get_ratings(league_code)
        standings = standings_service.get_standings(league_code)
        home_key = resolve_team_key(game.home_team)
        away_key = resolve_team_key(game.away_team)
        home_rating = select_preview_entry(ratings, home_key, "ratings")
        away_rating = select_preview_entry(ratings, away_key, "ratings")
        home_standing = select_preview_entry(standings, home_key, "standings")
        away_standing = select_preview_entry(standings, away_key, "standings")
    except Exception as exc:
        logger.exception("Failed to build preview score", extra={"game_id": game_id})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Preview score unavailable",
        ) from exc

    context = build_preview_context(game, home_rating, away_rating)
    tags = preview_tags(home_rating, away_rating, home_standing, away_standing)
    preview = GamePreviewScoreResponse(
        game_id=str(game.id),
        excitement_score=normalize_score(excitement_score(context)),
        quality_score=normalize_score(
            quality_score(home_rating, away_rating, home_standing, away_standing)
        ),
        tags=tags,
        nugget=generate_nugget(context, tags),
    )
    return preview


@router.get("/games/{game_id}", response_model=GameDetailResponse)
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
        # NHL: populate sport-specific lists, leave player_stats empty
        skaters = []
        goalies = []
        for player in game.player_boxscores:
            stats = player.stats or {}
            player_role = stats.get("player_role")
            if player_role == "goalie":
                goalies.append(serialize_nhl_goalie(player))
            else:
                # Default to skater for NHL players without explicit role
                skaters.append(serialize_nhl_skater(player))
        nhl_skaters = skaters
        nhl_goalies = goalies
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

    # Classify play tiers and build grouped plays
    if plays_entries and league_code:
        tiers = classify_all_tiers(plays_entries, league_code)
        for entry, t in zip(plays_entries, tiers, strict=False):
            entry.tier = t
        grouped_plays = group_tier3_plays(plays_entries, tiers)
    else:
        grouped_plays = None

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
            home_score=game.home_score,
            away_score=game.away_score,
            current_period=meta_current_period,
            game_clock=meta_game_clock,
        )

    meta = GameMeta(
        id=game.id,
        league_code=game.league.code if game.league else "UNKNOWN",
        season=game.season,
        season_type=getattr(game, "season_type", None),
        game_date=game.game_date,
        home_team=game.home_team.name if game.home_team else "Unknown",
        away_team=game.away_team.name if game.away_team else "Unknown",
        home_team_id=game.home_team.id if game.home_team else None,
        away_team_id=game.away_team.id if game.away_team else None,
        home_score=game.home_score,
        away_score=game.away_score,
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
        is_live=status_flags["is_live"],
        is_final=status_flags["is_final"],
        is_pregame=status_flags["is_pregame"],
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

    # MLB advanced stats (Statcast-derived)
    mlb_advanced_stats_list: list[MLBAdvancedTeamStats] | None = None
    if is_mlb and game.advanced_stats:
        mlb_advanced_stats_list = [
            MLBAdvancedTeamStats(
                team=stat.team.name if stat.team else "Unknown",
                is_home=stat.is_home,
                total_pitches=stat.total_pitches,
                z_swing_pct=stat.z_swing_pct,
                o_swing_pct=stat.o_swing_pct,
                z_contact_pct=stat.z_contact_pct,
                o_contact_pct=stat.o_contact_pct,
                balls_in_play=stat.balls_in_play,
                avg_exit_velo=stat.avg_exit_velo,
                hard_hit_pct=stat.hard_hit_pct,
                barrel_pct=stat.barrel_pct,
            )
            for stat in game.advanced_stats
        ]

    mlb_advanced_player_stats_list: list[MLBAdvancedPlayerStats] | None = None
    if is_mlb and game.player_advanced_stats:
        mlb_advanced_player_stats_list = [
            MLBAdvancedPlayerStats(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_home=stat.is_home,
                total_pitches=stat.total_pitches,
                zone_pitches=stat.zone_pitches,
                zone_swings=stat.zone_swings,
                zone_contact=stat.zone_contact,
                outside_pitches=stat.outside_pitches,
                outside_swings=stat.outside_swings,
                outside_contact=stat.outside_contact,
                balls_in_play=stat.balls_in_play,
                avg_exit_velo=stat.avg_exit_velo,
                hard_hit_count=stat.hard_hit_count,
                barrel_count=stat.barrel_count,
            )
            for stat in game.player_advanced_stats
        ]

    # MLB pitcher game stats (Statcast per-pitcher)
    mlb_pitcher_game_stats_list: list[MLBPitcherGameStatSchema] | None = None
    if is_mlb and game.pitcher_game_stats:
        mlb_pitcher_game_stats_list = [
            MLBPitcherGameStatSchema(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_starter=stat.is_starter or False,
                innings_pitched=stat.innings_pitched,
                batters_faced=stat.batters_faced,
                pitches_thrown=stat.pitches_thrown,
                strikeouts=stat.strikeouts,
                walks=stat.walks,
                zone_pitches=stat.zone_pitches,
                zone_swings=stat.zone_swings,
                zone_contact=stat.zone_contact,
                outside_pitches=stat.outside_pitches,
                outside_swings=stat.outside_swings,
                outside_contact=stat.outside_contact,
                balls_in_play=stat.balls_in_play,
                avg_exit_velo_against=stat.avg_exit_velo_against,
                hard_hit_against=stat.hard_hit_against,
                barrel_against=stat.barrel_against,
            )
            for stat in game.pitcher_game_stats
        ]

    # MLB fielding stats (per-game, loaded via game relationship)
    mlb_fielding_stats_list: list[MLBFieldingStatSchema] | None = None
    if is_mlb and game.fielding_stats:
        mlb_fielding_stats_list = [
            MLBFieldingStatSchema(
                team=row.team.name if row.team else "Unknown",
                player_name=row.player_name,
                position=row.position,
                outs_above_average=row.outs_above_average,
                defensive_runs_saved=row.defensive_runs_saved,
                uzr=row.uzr,
                errors=row.errors,
                assists=row.assists,
                putouts=row.putouts,
            )
            for row in game.fielding_stats
        ]

    # NBA advanced stats
    from .schemas.nba_advanced import NBAAdvancedTeamStats as NBAAdvTeamSchema
    from .schemas.nba_advanced import NBAAdvancedPlayerStats as NBAAdvPlayerSchema

    nba_advanced_stats_list: list[NBAAdvTeamSchema] | None = None
    is_nba = league_code == "NBA"
    if is_nba and game.nba_advanced_stats:
        nba_advanced_stats_list = [
            NBAAdvTeamSchema(
                team=stat.team.name if stat.team else "Unknown",
                is_home=stat.is_home,
                off_rating=stat.off_rating,
                def_rating=stat.def_rating,
                net_rating=stat.net_rating,
                pace=stat.pace,
                pie=stat.pie,
                efg_pct=stat.efg_pct,
                ts_pct=stat.ts_pct,
                fg_pct=stat.fg_pct,
                fg3_pct=stat.fg3_pct,
                ft_pct=stat.ft_pct,
                orb_pct=stat.orb_pct,
                drb_pct=stat.drb_pct,
                reb_pct=stat.reb_pct,
                ast_pct=stat.ast_pct,
                ast_ratio=stat.ast_ratio,
                ast_tov_ratio=stat.ast_tov_ratio,
                tov_pct=stat.tov_pct,
                ft_rate=stat.ft_rate,
                contested_shots=stat.contested_shots,
                deflections=stat.deflections,
                charges_drawn=stat.charges_drawn,
                loose_balls_recovered=stat.loose_balls_recovered,
                paint_points=stat.paint_points,
                fastbreak_points=stat.fastbreak_points,
                second_chance_points=stat.second_chance_points,
                points_off_turnovers=stat.points_off_turnovers,
                bench_points=stat.bench_points,
            )
            for stat in game.nba_advanced_stats
        ]

    nba_player_advanced_stats_list: list[NBAAdvPlayerSchema] | None = None
    if is_nba and game.nba_player_advanced_stats:
        nba_player_advanced_stats_list = [
            NBAAdvPlayerSchema(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_home=stat.is_home,
                minutes=stat.minutes,
                off_rating=stat.off_rating,
                def_rating=stat.def_rating,
                net_rating=stat.net_rating,
                usg_pct=stat.usg_pct,
                pie=stat.pie,
                ts_pct=stat.ts_pct,
                efg_pct=stat.efg_pct,
                contested_2pt_fga=stat.contested_2pt_fga,
                contested_2pt_fgm=stat.contested_2pt_fgm,
                uncontested_2pt_fga=stat.uncontested_2pt_fga,
                uncontested_2pt_fgm=stat.uncontested_2pt_fgm,
                contested_3pt_fga=stat.contested_3pt_fga,
                contested_3pt_fgm=stat.contested_3pt_fgm,
                uncontested_3pt_fga=stat.uncontested_3pt_fga,
                uncontested_3pt_fgm=stat.uncontested_3pt_fgm,
                pull_up_fga=stat.pull_up_fga,
                pull_up_fgm=stat.pull_up_fgm,
                catch_shoot_fga=stat.catch_shoot_fga,
                catch_shoot_fgm=stat.catch_shoot_fgm,
                speed=stat.speed,
                distance=stat.distance,
                touches=stat.touches,
                time_of_possession=stat.time_of_possession,
                contested_shots=stat.contested_shots,
                deflections=stat.deflections,
                charges_drawn=stat.charges_drawn,
                loose_balls_recovered=stat.loose_balls_recovered,
                screen_assists=stat.screen_assists,
            )
            for stat in game.nba_player_advanced_stats
        ]

    # NHL advanced stats (MoneyPuck-derived)
    from .schemas.nhl_advanced import (
        NHLAdvancedTeamStats as NHLAdvTeamSchema,
        NHLGoalieAdvancedStats as NHLGoalieSchema,
        NHLSkaterAdvancedStats as NHLSkaterSchema,
    )

    nhl_advanced_stats_list: list[NHLAdvTeamSchema] | None = None
    is_nhl = league_code == "NHL"
    if is_nhl and game.nhl_advanced_stats:
        nhl_advanced_stats_list = [
            NHLAdvTeamSchema(
                team=stat.team.name if stat.team else "Unknown",
                is_home=stat.is_home,
                xgoals_for=stat.xgoals_for,
                xgoals_against=stat.xgoals_against,
                xgoals_pct=stat.xgoals_pct,
                corsi_for=stat.corsi_for,
                corsi_against=stat.corsi_against,
                corsi_pct=stat.corsi_pct,
                fenwick_for=stat.fenwick_for,
                fenwick_against=stat.fenwick_against,
                fenwick_pct=stat.fenwick_pct,
                shots_for=stat.shots_for,
                shots_against=stat.shots_against,
                shooting_pct=stat.shooting_pct,
                save_pct=stat.save_pct,
                pdo=stat.pdo,
                high_danger_shots_for=stat.high_danger_shots_for,
                high_danger_goals_for=stat.high_danger_goals_for,
                high_danger_shots_against=stat.high_danger_shots_against,
                high_danger_goals_against=stat.high_danger_goals_against,
            )
            for stat in game.nhl_advanced_stats
        ]

    nhl_skater_advanced_stats_list: list[NHLSkaterSchema] | None = None
    if is_nhl and game.nhl_skater_advanced_stats:
        nhl_skater_advanced_stats_list = [
            NHLSkaterSchema(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_home=stat.is_home,
                xgoals_for=stat.xgoals_for,
                xgoals_against=stat.xgoals_against,
                on_ice_xgoals_pct=stat.on_ice_xgoals_pct,
                shots=stat.shots,
                goals=stat.goals,
                shooting_pct=stat.shooting_pct,
                goals_per_60=stat.goals_per_60,
                assists_per_60=stat.assists_per_60,
                points_per_60=stat.points_per_60,
                shots_per_60=stat.shots_per_60,
                game_score=stat.game_score,
            )
            for stat in game.nhl_skater_advanced_stats
        ]

    nhl_goalie_advanced_stats_list: list[NHLGoalieSchema] | None = None
    if is_nhl and game.nhl_goalie_advanced_stats:
        nhl_goalie_advanced_stats_list = [
            NHLGoalieSchema(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_home=stat.is_home,
                xgoals_against=stat.xgoals_against,
                goals_against=stat.goals_against,
                goals_saved_above_expected=stat.goals_saved_above_expected,
                save_pct=stat.save_pct,
                high_danger_save_pct=stat.high_danger_save_pct,
                medium_danger_save_pct=stat.medium_danger_save_pct,
                low_danger_save_pct=stat.low_danger_save_pct,
                shots_against=stat.shots_against,
            )
            for stat in game.nhl_goalie_advanced_stats
        ]

    # NFL advanced stats (nflverse-derived)
    from .schemas.nfl_advanced import (
        NFLAdvancedTeamStats as NFLAdvTeamSchema,
        NFLAdvancedPlayerStats as NFLAdvPlayerSchema,
    )

    nfl_advanced_stats_list: list[NFLAdvTeamSchema] | None = None
    is_nfl = league_code == "NFL"
    if is_nfl and game.nfl_advanced_stats:
        nfl_advanced_stats_list = [
            NFLAdvTeamSchema(
                team=stat.team.name if stat.team else "Unknown",
                is_home=stat.is_home,
                total_epa=stat.total_epa,
                pass_epa=stat.pass_epa,
                rush_epa=stat.rush_epa,
                epa_per_play=stat.epa_per_play,
                total_wpa=stat.total_wpa,
                success_rate=stat.success_rate,
                pass_success_rate=stat.pass_success_rate,
                rush_success_rate=stat.rush_success_rate,
                explosive_play_rate=stat.explosive_play_rate,
                avg_cpoe=stat.avg_cpoe,
                avg_air_yards=stat.avg_air_yards,
                avg_yac=stat.avg_yac,
                total_plays=stat.total_plays,
                pass_plays=stat.pass_plays,
                rush_plays=stat.rush_plays,
            )
            for stat in game.nfl_advanced_stats
        ]

    nfl_player_advanced_stats_list: list[NFLAdvPlayerSchema] | None = None
    if is_nfl and game.nfl_player_advanced_stats:
        nfl_player_advanced_stats_list = [
            NFLAdvPlayerSchema(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_home=stat.is_home,
                player_role=stat.player_role,
                total_epa=stat.total_epa,
                epa_per_play=stat.epa_per_play,
                pass_epa=stat.pass_epa,
                rush_epa=stat.rush_epa,
                receiving_epa=stat.receiving_epa,
                cpoe=stat.cpoe,
                air_epa=stat.air_epa,
                yac_epa=stat.yac_epa,
                air_yards=stat.air_yards,
                total_wpa=stat.total_wpa,
                success_rate=stat.success_rate,
                plays=stat.plays,
            )
            for stat in game.nfl_player_advanced_stats
        ]

    from ...services.play_tiers import enrich_play_entries

    if plays_entries and league_code:
        home_abbr_val = game.home_team.abbreviation if game.home_team else None
        away_abbr_val = game.away_team.abbreviation if game.away_team else None
        if home_abbr_val and away_abbr_val:
            enrich_play_entries(plays_entries, league_code, home_abbr_val, away_abbr_val)

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
