# Scheduler And Jobs

The scraper Celery app defines two beat-scheduled runtime paths. The repository
is not currently deployed, so these describe code behavior rather than active
production execution.

## Authoritative Schedule

Defined in `scraper/sports_scraper/celery_app.py`:

| Beat entry | Task | Cadence | Queue |
| --- | --- | --- | --- |
| `calendar-game-stubs-every-15m` | `poll_game_calendars` | every 15 minutes | `sports-scraper` |
| `catchup-pbp-stats-every-5m` | `poll_live_pbp` | every 5 minutes | `sports-scraper` |

`refresh_card_feeds` is included and routed to `sports-scraper`, but it is not
beat-scheduled. It remains available for explicit local use and in the gated
historical deployment procedure.

## Task Behavior

`poll_game_calendars` creates or updates lightweight game stubs for NBA, NHL,
MLB, NCAAB, and NFL for today through the seven-day lookahead window. It is
idempotent: existing games are updated rather than duplicated.

`poll_live_pbp` refreshes:

- play-by-play
- player box scores
- team box scores
- status and final score fields as returned by the league integrations

The task uses a Redis lock so slow runs do not overlap.

The task selects active games through `scraper/sports_scraper/services/active_games.py`. It prioritizes scheduled, live, and recently final games near the catch-up window when play-by-play or box score data is stale or missing.

On worker startup, the Celery app clears stale Redis locks and marks interrupted scrape/job runs so a previous crash does not permanently block the next run.

## Task Hold

The Redis key `sports:tasks_held=1` makes beat-scheduled tasks skip execution. Manual triggers pass a `manual_trigger` header and may bypass the hold.

Admin routes:

- `GET /api/admin/tasks/hold`
- `PUT /api/admin/tasks/hold`
- `GET /api/admin/tasks/registry`
- `POST /api/admin/tasks/trigger`
- `GET /api/admin/social/session-health`

`/api/admin/social/session-health` reads the most recent Playwright session
health snapshot from Redis. It does not schedule or run a social scraper.

The admin trigger registry exposes only `poll_live_pbp`. `poll_game_calendars`
is beat-scheduled but not exposed for manual triggering through the admin task
registry.

Manual trigger request bodies use snake_case:

```json
{
  "task_name": "poll_live_pbp",
  "args": []
}
```

## Not Scheduled

The legacy full scheduler is not supported. There are no active beat entries
for ingestion sweeps, odds sync, golf, social scraping, analytics, simulator,
realtime orchestration, training, or 5-second live polling.
