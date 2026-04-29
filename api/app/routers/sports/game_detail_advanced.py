"""Advanced stats serialization helpers for game detail endpoint."""

from __future__ import annotations

from .schemas import (
    MLBAdvancedPlayerStats,
    MLBAdvancedTeamStats,
    MLBFieldingStatSchema,
    MLBPitcherGameStatSchema,
)
from .schemas.nba_advanced import (
    NBAAdvancedPlayerStats as NBAAdvPlayerSchema,
)
from .schemas.nba_advanced import (
    NBAAdvancedTeamStats as NBAAdvTeamSchema,
)
from .schemas.ncaab_advanced import (
    NCAABAdvancedPlayerStats as NCAABAdvPlayerSchema,
)
from .schemas.ncaab_advanced import (
    NCAABAdvancedTeamStats as NCAABAdvTeamSchema,
)
from .schemas.nfl_advanced import (
    NFLAdvancedPlayerStats as NFLAdvPlayerSchema,
)
from .schemas.nfl_advanced import (
    NFLAdvancedTeamStats as NFLAdvTeamSchema,
)
from .schemas.nhl_advanced import (
    NHLAdvancedTeamStats as NHLAdvTeamSchema,
)
from .schemas.nhl_advanced import (
    NHLGoalieAdvancedStats as NHLGoalieSchema,
)
from .schemas.nhl_advanced import (
    NHLSkaterAdvancedStats as NHLSkaterSchema,
)


def serialize_mlb_advanced(game) -> tuple[list | None, list | None, list | None, list | None]:
    """Serialize MLB advanced stats (team, player, pitcher, fielding)."""
    # MLB advanced stats (Statcast-derived)
    mlb_advanced_stats_list: list[MLBAdvancedTeamStats] | None = None
    if game.advanced_stats:
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
    if game.player_advanced_stats:
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
    if game.pitcher_game_stats:
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
    if game.fielding_stats:
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

    return (
        mlb_advanced_stats_list,
        mlb_advanced_player_stats_list,
        mlb_pitcher_game_stats_list,
        mlb_fielding_stats_list,
    )


def serialize_nba_advanced(game) -> tuple[list | None, list | None]:
    """Serialize NBA advanced stats (team, player)."""
    nba_advanced_stats_list: list[NBAAdvTeamSchema] | None = None
    if game.nba_advanced_stats:
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
    if game.nba_player_advanced_stats:
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

    return nba_advanced_stats_list, nba_player_advanced_stats_list


def serialize_nhl_advanced(game) -> tuple[list | None, list | None, list | None]:
    """Serialize NHL advanced stats (team, skater, goalie)."""
    nhl_advanced_stats_list: list[NHLAdvTeamSchema] | None = None
    if game.nhl_advanced_stats:
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
    if game.nhl_skater_advanced_stats:
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
    if game.nhl_goalie_advanced_stats:
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

    return nhl_advanced_stats_list, nhl_skater_advanced_stats_list, nhl_goalie_advanced_stats_list


def serialize_nfl_advanced(game) -> tuple[list | None, list | None]:
    """Serialize NFL advanced stats (team, player)."""
    nfl_advanced_stats_list: list[NFLAdvTeamSchema] | None = None
    if game.nfl_advanced_stats:
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
    if game.nfl_player_advanced_stats:
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

    return nfl_advanced_stats_list, nfl_player_advanced_stats_list


def serialize_ncaab_advanced(game) -> tuple[list | None, list | None]:
    """Serialize NCAAB advanced stats (team, player)."""
    ncaab_advanced_stats_list: list[NCAABAdvTeamSchema] | None = None
    if game.ncaab_advanced_stats:
        ncaab_advanced_stats_list = [
            NCAABAdvTeamSchema(
                team=stat.team.name if stat.team else "Unknown",
                is_home=stat.is_home,
                possessions=stat.possessions,
                off_rating=stat.off_rating,
                def_rating=stat.def_rating,
                net_rating=stat.net_rating,
                pace=stat.pace,
                off_efg_pct=stat.off_efg_pct,
                off_tov_pct=stat.off_tov_pct,
                off_orb_pct=stat.off_orb_pct,
                off_ft_rate=stat.off_ft_rate,
                def_efg_pct=stat.def_efg_pct,
                def_tov_pct=stat.def_tov_pct,
                def_orb_pct=stat.def_orb_pct,
                def_ft_rate=stat.def_ft_rate,
                fg_pct=stat.fg_pct,
                three_pt_pct=stat.three_pt_pct,
                ft_pct=stat.ft_pct,
                three_pt_rate=stat.three_pt_rate,
            )
            for stat in game.ncaab_advanced_stats
        ]

    ncaab_player_advanced_stats_list: list[NCAABAdvPlayerSchema] | None = None
    if game.ncaab_player_advanced_stats:
        ncaab_player_advanced_stats_list = [
            NCAABAdvPlayerSchema(
                team=stat.team.name if stat.team else "Unknown",
                player_name=stat.player_name,
                is_home=stat.is_home,
                minutes=stat.minutes,
                off_rating=stat.off_rating,
                usg_pct=stat.usg_pct,
                ts_pct=stat.ts_pct,
                efg_pct=stat.efg_pct,
                game_score=stat.game_score,
                points=stat.points,
                rebounds=stat.rebounds,
                assists=stat.assists,
                steals=stat.steals,
                blocks=stat.blocks,
                turnovers=stat.turnovers,
            )
            for stat in game.ncaab_player_advanced_stats
        ]

    return ncaab_advanced_stats_list, ncaab_player_advanced_stats_list
