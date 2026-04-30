# Scheduler & background jobs

## Authoritative schedule

**Celery Beat** for ingestion, polling, golf, and related tasks is defined in **`scraper/sports_scraper/celery_app.py`** (`_polling_schedule`, `_scheduled_tasks`, `_live_polling_schedule`, merged into `app.conf.beat_schedule`). Comments in that file use **UTC** times and note the US/Eastern interpretation for daily jobs.

### Queue layout (scraper Celery app)

| Queue | Typical workloads |
|-------|-------------------|
| `sports-scraper` | Default ingestion, PBP polling, odds sync, flow triggers, non-social tasks |
| `social-scraper` | X/Twitter collection (single Playwright session; concurrency kept low) |
| `social-bulk` | Bulk social mapping (`map_social_to_games`) |

Routes are set in `app.conf.task_routes` in the same module.

### Admin “hold”

Redis key **`sports:tasks_held`** (when set to `1`) causes beat-scheduled tasks to skip execution (`_HoldAwareTask`). Manual triggers can pass `manual_trigger` to bypass. Implementation: `scraper/sports_scraper/celery_app.py`.

### High-frequency summary (verify exact crontab in code)

- **Every 5s:** `poll_live_pbp(True)` (live-only path), `live_orchestrator_tick`.
- **Every minute (hour windows excluding quiet hours):** `update_game_states`, `poll_live_pbp` (full path).
- **Every 3 min:** `sync_mainline_odds`.
- **Every 15 min:** `sync_prop_odds`, `poll_game_calendars`.
- **Daily (UTC):** `run_scheduled_ingestion` (08:30 UTC — aligns with 3:30 AM Eastern in standard time), `run_daily_sweep`, `sweep_missing_flows`, golf tasks as scheduled.
- **Social (UTC minute marks):** `collect_game_social` hourly at `:00`; `map_social_to_games` at `:15` and `:45`; `check_playwright_session_health` at `:10` and `:40` (see `_live_polling_schedule` in `celery_app.py`).

### API Celery app (`api/app/celery_app.py`)

Separate Celery application for API-side tasks (training, batch simulations, webhooks, etc.). Broker defaults to `REDIS_URL` / `CELERY_BROKER_URL`. Beat schedules for **analytics** jobs that use the `celery` queue appear in **`scraper/sports_scraper/celery_app.py`** (`record_completed_outcomes`, `refresh_mlb_forecasts`, `generate_pipeline_coverage_report`) — they target the API worker queue on the **same Redis broker** but a different Celery app name.

Docker: **`api-worker`** and **`api-training-worker`** run workers for the API Celery app; **`scraper`** + **`scraper-beat`** run the scraper app. See [Infrastructure](ops/infra.md).

## Manual operations

- **Admin UI:** Control Panel dispatches registered Celery tasks (`/api/admin/.../tasks` — see [API](api.md)).
- **On-demand scrapes:** `POST /api/admin/sports/scraper/runs` (and related admin routes).

## What runs automatically vs manually

| Automatic | Manual / on-demand |
|-----------|-------------------|
| Beat schedule above | Admin task triggers, single-game rescrape, pipeline runs from UI |
| Stripe webhooks (HTTP POST) | Database restores, migrations (`migrate` service) |
| Flow generation on LIVE→FINAL (ORM hook + sweep fallback) | Bulk timeline regeneration endpoints |
