# Data Sources

The catch-up worker refreshes play-by-play and box score data for supported leagues.

## Active Data Types

- Game schedule/status metadata
- Play-by-play
- Player stats
- Team stats
- Score fields used by game detail and, for live games with play state, `liveSnapshot`

## League Integrations

| League | Data Used |
| --- | --- |
| NBA | Game IDs, play-by-play, player/team box scores |
| NHL | Game IDs, play-by-play, player/team box scores |
| MLB | Game IDs, play-by-play, player/team box scores |
| NCAAB | CBB/NCAA IDs, play-by-play, player/team box scores |

The active scheduler calls `poll_live_pbp` every five minutes. See [Scheduler and jobs](../scheduler-and-jobs.md).

The worker does not run broad historical backfills automatically. It refreshes
games selected by the active-game resolver around the current catch-up window.

## Not Active

The current Celery app does not schedule odds, golf, social scraping, model
training, simulator, analytics, timeline, or narrative pipeline jobs. Some
manual admin routes for pipeline and timeline inspection or generation remain
mounted by the API; they are separate from automatic ingestion.
