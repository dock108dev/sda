"""Shared helper utilities for sports game endpoints."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import Select
from sqlalchemy.sql import or_

from ...celery_client import get_celery_app
from ...db import AsyncSession
from ...db.scraper import SportsScrapeRun
from ...db.social import TeamSocialPost
from ...db.sports import SportsGame, SportsLeague, SportsTeam
from ...game_metadata.models import GameContext, StandingsEntry, TeamRatings
from ...services.game_status import compute_status_flags
from ...utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc, to_et_date
from .schemas import GameSummary, JobResponse, LiveSnapshot, ScrapeRunConfig, SocialPostEntry

logger = logging.getLogger(__name__)

PREVIEW_TOP25_ELO_THRESHOLD = 1600.0
PREVIEW_TOP_RATED_SEED_THRESHOLD = 4
PREVIEW_BIG_NAME_SEED_THRESHOLD = 5
PREVIEW_SEEDING_BATTLE_SEED_THRESHOLD = 8
PREVIEW_NATIONAL_ELO_THRESHOLD = 1650.0
PREVIEW_ELO_SPREAD_DIVISOR = 30.0
PREVIEW_TOTAL_BASE = 135.0
PREVIEW_TOTAL_ELO_BASELINE = 1500.0
PREVIEW_TOTAL_ELO_DIVISOR = 20.0
PREVIEW_TOTAL_MIN = 100.0
PREVIEW_TOTAL_MAX = 180.0


_FINAL_STATUSES = ("final", "completed", "official")


def apply_game_filters(
    stmt: Select[tuple[SportsGame]],
    leagues: Sequence[str] | None,
    season: int | None,
    team: str | None,
    start_date: date | None,
    end_date: date | None,
    missing_boxscore: bool,
    missing_player_stats: bool,
    missing_odds: bool,
    missing_social: bool,
    missing_any: bool,
    final_only: bool = False,
) -> Select[tuple[SportsGame]]:
    """Apply filtering options for list endpoints."""
    if final_only:
        stmt = stmt.where(SportsGame.status.in_(_FINAL_STATUSES))

    if leagues:
        league_codes = [code.upper() for code in leagues]
        stmt = stmt.where(SportsGame.league.has(SportsLeague.code.in_(league_codes)))

    if season is not None:
        stmt = stmt.where(SportsGame.season == season)

    if team:
        pattern = f"%{team}%"
        stmt = stmt.where(
            or_(
                SportsGame.home_team.has(SportsTeam.name.ilike(pattern)),
                SportsGame.away_team.has(SportsTeam.name.ilike(pattern)),
                SportsGame.home_team.has(SportsTeam.short_name.ilike(pattern)),
                SportsGame.away_team.has(SportsTeam.short_name.ilike(pattern)),
                SportsGame.home_team.has(SportsTeam.abbreviation.ilike(pattern)),
                SportsGame.away_team.has(SportsTeam.abbreviation.ilike(pattern)),
            )
        )

    if start_date:
        # Use ET sports-calendar boundaries so late-night ET games
        # (which are early-morning UTC) appear on the correct day.
        stmt = stmt.where(SportsGame.game_date >= start_of_et_day_utc(start_date))

    if end_date:
        stmt = stmt.where(SportsGame.game_date < end_of_et_day_utc(end_date))

    if missing_boxscore:
        stmt = stmt.where(~SportsGame.team_boxscores.any())
    if missing_player_stats:
        stmt = stmt.where(~SportsGame.player_boxscores.any())
    if missing_odds:
        stmt = stmt.where(~SportsGame.odds.any())
    if missing_social:
        stmt = stmt.where(~SportsGame.social_posts.any())
    if missing_any:
        stmt = stmt.where(
            or_(
                ~SportsGame.team_boxscores.any(),
                ~SportsGame.player_boxscores.any(),
                ~SportsGame.odds.any(),
            )
        )
    return stmt


def clamp_score(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp scores to a consistent 0-100 range."""
    return max(minimum, min(maximum, value))


def normalize_score(value: float) -> int:
    """Normalize score values for API responses."""
    return int(round(clamp_score(value)))


def resolve_team_key(team: SportsTeam) -> str:
    """Resolve the identifier used by ratings/standings feeds."""
    if team.external_ref:
        return team.external_ref
    for code in team.external_codes.values():
        if isinstance(code, str) and code.strip():
            return code
    return str(team.id)


def select_preview_entry(
    entries: Sequence[StandingsEntry] | Sequence[TeamRatings],
    team_key: str,
    entry_label: str,
) -> StandingsEntry | TeamRatings:
    """Select rating/standings entry for a team. Fails fast if not found."""
    for entry in entries:
        if entry.team_id == team_key:
            return entry
    raise ValueError(f"Preview score missing {entry_label} data for team {team_key}")


def projected_spread(home_rating: TeamRatings, away_rating: TeamRatings) -> float:
    """Estimate point spread based on ELO."""
    return (home_rating.elo - away_rating.elo) / PREVIEW_ELO_SPREAD_DIVISOR


def projected_total(home_rating: TeamRatings, away_rating: TeamRatings) -> float:
    """Estimate total based on average ELO."""
    average_elo = (home_rating.elo + away_rating.elo) / 2
    raw_total = PREVIEW_TOTAL_BASE + (
        (average_elo - PREVIEW_TOTAL_ELO_BASELINE) / PREVIEW_TOTAL_ELO_DIVISOR
    )
    return clamp_score(raw_total, PREVIEW_TOTAL_MIN, PREVIEW_TOTAL_MAX)


def preview_tags(
    home_rating: TeamRatings,
    away_rating: TeamRatings,
    home_standing: StandingsEntry,
    away_standing: StandingsEntry,
) -> list[str]:
    """Build preview tags based on ratings + standings context."""
    tags: set[str] = set()
    top_two = max(home_standing.conference_rank, away_standing.conference_rank) <= 2
    if top_two:
        tags.update({"conference_lead", "top_two_conference"})

    if min(home_rating.elo, away_rating.elo) >= PREVIEW_TOP25_ELO_THRESHOLD:
        tags.add("top25_matchup")

    seeds = [
        seed
        for seed in (home_rating.projected_seed, away_rating.projected_seed)
        if seed is not None
    ]
    if len(seeds) == 2:
        if max(seeds) <= PREVIEW_TOP_RATED_SEED_THRESHOLD:
            tags.update({"top_rated", "tournament_preview"})
        if max(seeds) <= PREVIEW_SEEDING_BATTLE_SEED_THRESHOLD:
            tags.add("seeding_battle")

    return sorted(tags)


def build_preview_context(
    game: SportsGame,
    home_rating: TeamRatings,
    away_rating: TeamRatings,
) -> GameContext:
    """Assemble a GameContext to generate preview scores. Fails fast if teams/league missing."""
    if not game.home_team or not game.away_team:
        raise ValueError(f"Game {game.id} missing team mappings")
    if not game.league:
        raise ValueError(f"Game {game.id} missing league")

    rivalry = home_rating.conference == away_rating.conference
    projected_spread_value = projected_spread(home_rating, away_rating)
    projected_total_value = projected_total(home_rating, away_rating)
    has_big_name_players = any(
        seed is not None and seed <= PREVIEW_BIG_NAME_SEED_THRESHOLD
        for seed in (home_rating.projected_seed, away_rating.projected_seed)
    )
    playoff_implications = all(
        seed is not None for seed in (home_rating.projected_seed, away_rating.projected_seed)
    )
    national_broadcast = (home_rating.elo + away_rating.elo) / 2 >= PREVIEW_NATIONAL_ELO_THRESHOLD

    return GameContext(
        game_id=str(game.id),
        home_team=game.home_team.name,
        away_team=game.away_team.name,
        league=game.league.code,
        start_time=game.game_date,
        rivalry=rivalry,
        projected_spread=projected_spread_value,
        has_big_name_players=has_big_name_players,
        coach_vs_former_team=False,
        playoff_implications=playoff_implications,
        national_broadcast=national_broadcast,
        projected_total=projected_total_value,
    )


def summarize_game(
    game: SportsGame,
    has_flow: bool | None = None,
) -> GameSummary:
    """Summarize game fields for list responses. Fails fast if core data missing.

    Args:
        game: The game to summarize
        has_flow: Whether the game has a flow in SportsGameFlow table.
            If None, defaults to False.
    """
    if not game.league:
        raise ValueError(f"Game {game.id} missing league")
    if not game.home_team or not game.away_team:
        raise ValueError(f"Game {game.id} missing team mappings")

    has_boxscore = bool(game.team_boxscores)
    has_player_stats = bool(game.player_boxscores)
    has_odds = bool(game.odds)
    social_posts = getattr(game, "social_posts", [])
    has_social = bool(social_posts)
    social_post_count = len(social_posts)
    plays = getattr(game, "plays", [])
    has_pbp = bool(plays)
    play_count = len(plays)
    # has_flow is now passed in from caller (checked against SportsGameFlow table)
    if has_flow is None:
        has_flow = False

    # Compute derived metrics (odds already loaded via selectinload)
    from ...services.derived_metrics import compute_derived_metrics
    from ...services.team_colors import get_matchup_colors

    odds = getattr(game, "odds", None) or []
    derived = compute_derived_metrics(game, odds) if odds else {}

    matchup_colors = get_matchup_colors(
        game.home_team.color_light_hex,
        game.home_team.color_dark_hex,
        game.away_team.color_light_hex,
        game.away_team.color_dark_hex,
    )

    # Latest play's period/clock for live score context
    latest_play = max(plays, key=lambda p: p.play_index, default=None) if plays else None
    current_period = getattr(latest_play, "quarter", None) if latest_play else None
    game_clock_val = getattr(latest_play, "game_clock", None) if latest_play else None

    status_flags = compute_status_flags(game.status)
    league_code = game.league.code

    from ...services.period_labels import period_label, time_label

    current_period_label: str | None = None
    live_snapshot: LiveSnapshot | None = None
    if current_period is not None:
        current_period_label = period_label(current_period, league_code)
        live_snapshot = LiveSnapshot(
            period_label=current_period_label,
            time_label=time_label(current_period, game_clock_val, league_code),
            home_score=game.home_score,
            away_score=game.away_score,
            current_period=current_period,
            game_clock=game_clock_val,
        )

    from ...services.date_section import classify_date_section

    date_section = classify_date_section(game.game_date)

    return GameSummary(
        id=game.id,
        league_code=league_code,
        game_date=game.game_date,
        status=game.status,
        home_team=game.home_team.name,
        away_team=game.away_team.name,
        home_score=game.home_score,
        away_score=game.away_score,
        current_period=current_period,
        game_clock=game_clock_val,
        has_boxscore=has_boxscore,
        has_player_stats=has_player_stats,
        has_odds=has_odds,
        has_social=has_social,
        has_pbp=has_pbp,
        has_flow=has_flow,
        has_advanced_stats=getattr(game, "last_advanced_stats_at", None) is not None,
        play_count=play_count,
        social_post_count=social_post_count,
        scrape_version=getattr(game, "scrape_version", None),
        last_scraped_at=game.last_scraped_at,
        last_ingested_at=game.last_ingested_at,
        last_pbp_at=game.last_pbp_at,
        last_social_at=game.last_social_at,
        last_odds_at=game.last_odds_at,
        last_advanced_stats_at=getattr(game, "last_advanced_stats_at", None),
        derived_metrics=derived,
        home_team_abbr=game.home_team.abbreviation,
        away_team_abbr=game.away_team.abbreviation,
        home_team_color_light=matchup_colors["homeLightHex"],
        home_team_color_dark=matchup_colors["homeDarkHex"],
        away_team_color_light=matchup_colors["awayLightHex"],
        away_team_color_dark=matchup_colors["awayDarkHex"],
        is_live=status_flags["is_live"],
        is_final=status_flags["is_final"],
        is_pregame=status_flags["is_pregame"],
        is_truly_completed=status_flags["is_truly_completed"],
        read_eligible=status_flags["read_eligible"],
        current_period_label=current_period_label,
        live_snapshot=live_snapshot,
        date_section=date_section,
    )


def resolve_team_abbreviation(game: SportsGame, post: TeamSocialPost) -> str:
    """Resolve a team's abbreviation for a social post entry. Fails fast if not resolvable."""
    if hasattr(post, "team") and post.team and post.team.abbreviation:
        return post.team.abbreviation
    if hasattr(post, "team_id"):
        if game.home_team and game.home_team.id == post.team_id:
            return game.home_team.abbreviation
        if game.away_team and game.away_team.id == post.team_id:
            return game.away_team.abbreviation
    raise ValueError(f"Cannot resolve team abbreviation for post {post.id} in game {game.id}")


def _total_interactions(post: TeamSocialPost) -> int:
    """Sum engagement metrics for sorting priority."""
    return (post.likes_count or 0) + (post.retweets_count or 0) + (post.replies_count or 0)


def serialize_social_posts(
    game: SportsGame,
    posts: Sequence[TeamSocialPost],
) -> list[SocialPostEntry]:
    """Serialize social posts for API responses, sorted by total interactions desc."""
    sorted_posts = sorted(posts, key=_total_interactions, reverse=True)
    entries: list[SocialPostEntry] = []
    for post in sorted_posts:
        entries.append(
            SocialPostEntry(
                id=post.id,
                post_url=post.post_url,
                posted_at=post.posted_at,
                has_video=post.has_video,
                team_abbreviation=resolve_team_abbreviation(game, post),
                tweet_text=post.tweet_text,
                video_url=post.video_url,
                image_url=post.image_url,
                source_handle=post.source_handle,
                media_type=post.media_type,
                game_phase=post.game_phase,
                likes_count=post.likes_count,
                retweets_count=post.retweets_count,
                replies_count=post.replies_count,
            )
        )
    return entries


async def enqueue_single_game_run(
    session: AsyncSession,
    game: SportsGame,
    *,
    include_boxscores: bool,
    include_odds: bool,
    scraper_type: str,
) -> JobResponse:
    """Create a scrape run and enqueue it for a single game."""

    await session.refresh(game, attribute_names=["league"])
    if not game.league:
        raise HTTPException(status_code=400, detail="League missing for game")

    config = ScrapeRunConfig(
        league_code=game.league.code,
        season=game.season,
        season_type=getattr(game, "season_type", "regular"),
        start_date=to_et_date(game.game_date),
        end_date=to_et_date(game.game_date),
        boxscores=include_boxscores,
        odds=include_odds,
        social=False,
        pbp=False,
        only_missing=False,
        updated_before=None,
        include_books=None,
    )

    run = SportsScrapeRun(
        scraper_type=scraper_type,
        league_id=game.league_id,
        season=game.season,
        season_type=getattr(game, "season_type", "regular"),
        start_date=datetime.combine(to_et_date(game.game_date), datetime.min.time()),
        end_date=datetime.combine(to_et_date(game.game_date), datetime.min.time()),
        status="pending",
        requested_by="admin_boxscore_viewer",
        config=config.model_dump(by_alias=False),
    )
    session.add(run)
    await session.flush()

    worker_payload = config.to_worker_payload()
    celery_app = get_celery_app()
    async_result = celery_app.send_task(
        "run_scrape_job",
        args=[run.id, worker_payload],
        queue="sports-scraper",
        routing_key="sports-scraper",
    )
    run.job_id = async_result.id

    return JobResponse(run_id=run.id, job_id=async_result.id, message="Job enqueued")
