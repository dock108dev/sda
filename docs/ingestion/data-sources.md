# Data Sources

The catch-up worker creates upcoming game stubs and refreshes play-by-play plus
box score data for supported leagues.

## Supported Data Types

- Game schedule/status metadata
- Play-by-play
- Player stats
- Team stats
- Score fields used by game detail and, for live games with play state, `liveSnapshot`
- Materialized normalized card feeds when a local operator explicitly calls the
  refresh path; the inactive historical deployment procedure also retains it

## League Integrations

| League | Scheduled data used |
| --- | --- |
| NBA | Calendar stubs, game IDs, play-by-play, player/team box scores |
| NHL | Calendar stubs, game IDs, play-by-play, player/team box scores |
| MLB | Calendar stubs, game IDs, play-by-play, player/team box scores |
| NCAAB | Calendar stubs, CBB/NCAA IDs, play-by-play, player/team box scores |
| NFL | Calendar stubs only in the active beat schedule |

The scheduler definition calls `poll_game_calendars` every 15 minutes and
`poll_live_pbp` every five minutes when the local runtime is running. See
[Scheduler and jobs](../scheduler-and-jobs.md).

The worker does not run broad historical backfills automatically. It refreshes
games selected by the active-game resolver around the current catch-up window.

## Not Active

The current Celery beat app does not schedule odds, golf, social scraping,
model training, simulator, analytics, timeline, or narrative pipeline jobs.
Some manual admin routes for pipeline, timeline, and card-feed materialization
remain mounted by the API; they are separate from automatic ingestion.
