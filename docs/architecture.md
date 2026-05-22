# Architecture

Sports Data Admin is now a catch-up data service for Scroll Down Sports. It keeps one API path and one background refresh path.

## Runtime Shape

```text
External league feeds
        |
        v
scraper Celery worker: poll_live_pbp
        |
        v
PostgreSQL: games, plays, player stats, team stats
        |
        v
FastAPI: /api/admin/sports/*
        |
        v
Scroll Down clients
```

Redis is used for Celery broker/backend and the global task hold flag. The API reads PostgreSQL directly and uses OpenAI only for optional homepage game context copy.

The repository still contains historical modules and migrations. Active production behavior is defined by what is imported by `api/main.py`, scheduled by `scraper/sports_scraper/celery_app.py`, and run by `infra/docker-compose.yml`.

## Components

### API

Authoritative entrypoint: `api/main.py`.

Mounted product routes:

- `GET /api/admin/sports/games`
- `GET /api/admin/sports/games/{game_id}`
- `GET /api/admin/sports/games/{game_id}/context`

The list endpoint is spoiler-light and omits the detail payload's top-level score. Game detail includes score, play-by-play, player stats, team stats, and final box score data for the scroll-down experience.

### Scraper

Authoritative Celery app: `scraper/sports_scraper/celery_app.py`.

Only one task is routed and scheduled:

- `poll_live_pbp`, every 5 minutes

The task refreshes play-by-play, team stats, player stats, and box score data for games around the active catch-up window.

### Infrastructure

Authoritative compose file: `infra/docker-compose.yml`.

Application services:

- `api`
- `scraper`
- `scraper-beat`
- `web`
- `migrate`
- `postgres`
- `redis`
- `backup`
- `log-relay`

The removed full-stack services are not supported: API workers, training workers, odds workers, social workers, golf jobs, realtime streams, and simulator/analytics routes.

## CI Boundary

GitHub Actions still runs broad historical checks and tests. Passing CI does not mean every historical module is part of the active runtime; the runtime boundary is the mounted API, scheduled Celery task, and compose service set above.
