"""Celery tasks registry — re-exports all tasks for Celery discovery.

Import directly from specific task modules:
- scrape_tasks: Ingestion
- odds_tasks: Odds sync (mainline every 15 min, props every 60 min)
- timeline_tasks: Timeline generation
- flow_tasks: Game flow generation
- social_tasks: Team-centric social collection
- final_whistle_tasks: Post-game social scrape on FINAL transition
- polling_tasks: Game-state-machine polling
- flow_trigger_tasks: Edge-triggered flow generation
- sweep_tasks: Daily sweep / truth repair
- utility_tasks: Cache clearing and utilities
"""

from __future__ import annotations

from .final_whistle_tasks import (
    run_final_whistle_social,
)
from .flow_tasks import (
    run_scheduled_flow_generation,
    run_scheduled_nba_flow_generation,
    run_scheduled_ncaab_flow_generation,
    run_scheduled_nhl_flow_generation,
)
from .flow_trigger_tasks import (
    trigger_flow_for_game,
)
from .odds_tasks import (
    sync_mainline_odds,
    sync_prop_odds,
)
from .polling_tasks import (
    poll_live_pbp_task,
    update_game_states_task,
)

# Re-export all tasks for Celery discovery
from .scrape_tasks import (
    run_scheduled_ingestion,
    run_scrape_job,
)
from .social_tasks import (
    collect_game_social,
    collect_social_for_league,
    collect_team_social,
    handle_social_task_failure,
    map_social_to_games,
)
from .sweep_tasks import (
    run_daily_sweep,
)
from .timeline_tasks import (
    generate_missing_timelines_task,
    regenerate_timeline_task,
    run_scheduled_timeline_generation,
)
from .utility_tasks import (
    clear_scraper_cache_task,
)
from .live_orchestrator import (
    live_orchestrator_tick,
)
from .live_odds_tasks import (
    poll_live_odds_mainline,
    poll_live_odds_props,
)

__all__ = [
    "run_final_whistle_social",
    "run_scrape_job",
    "run_scheduled_ingestion",
    "sync_mainline_odds",
    "sync_prop_odds",
    "generate_missing_timelines_task",
    "regenerate_timeline_task",
    "run_scheduled_timeline_generation",
    "run_scheduled_nba_flow_generation",
    "run_scheduled_nhl_flow_generation",
    "run_scheduled_ncaab_flow_generation",
    "run_scheduled_flow_generation",
    "collect_game_social",
    "collect_social_for_league",
    "collect_team_social",
    "handle_social_task_failure",
    "map_social_to_games",
    "update_game_states_task",
    "poll_live_pbp_task",
    "trigger_flow_for_game",
    "run_daily_sweep",
    "clear_scraper_cache_task",
    "live_orchestrator_tick",
    "poll_live_odds_mainline",
    "poll_live_odds_props",
]
