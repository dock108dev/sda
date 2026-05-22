# Scheduler And Jobs

The scraper Celery app has one production execution path.

## Authoritative Schedule

Defined in `scraper/sports_scraper/celery_app.py`:

| Beat entry | Task | Cadence | Queue |
| --- | --- | --- | --- |
| `catchup-pbp-stats-every-5m` | `poll_live_pbp` | every 5 minutes | `sports-scraper` |

No other scraper tasks are routed or beat-scheduled by the active Celery app.

## Task Behavior

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

## Removed Schedules

The legacy full scheduler is not supported. There are no active beat entries for ingestion sweeps, odds sync, golf, social scraping, analytics, realtime orchestration, training, or 5-second live polling.
