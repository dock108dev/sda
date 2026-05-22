# Database

PostgreSQL is the source of truth for catch-up data.

## Core Tables

| Table | Purpose |
| --- | --- |
| `sports_leagues` | League metadata and codes |
| `sports_teams` | Team metadata and abbreviations |
| `sports_games` | Game identity, teams, dates, status, scores, and data freshness timestamps |
| `sports_game_plays` | Ordered play-by-play events |
| `sports_player_boxscores` | Per-player stat lines |
| `sports_team_boxscores` | Per-team stat lines |
| `sports_scrape_runs` | Historical scrape run records |
| `sports_job_runs` | Celery task run records |

## Catch-Up Query Shape

The homepage list reads `sports_games` with league/team filters and a default time window of `-72h` to `+48h`.

Game detail joins or separately loads:

- `sports_game_plays`
- `sports_player_boxscores`
- `sports_team_boxscores`

The homepage does not expose the detail payload's top-level score. Detail endpoints expose score, ordered plays, player stats, and team stats.

Important freshness columns on `sports_games`:

- `last_scraped_at`
- `last_ingested_at`
- `last_pbp_at`
- `last_boxscore_at`

## Migrations

Alembic migrations live in `api/alembic/versions/`. Use the `migrate` Docker service for local and production migrations.

```bash
cd infra
docker compose --profile dev run --rm migrate
```

## Notes

Legacy odds, golf, social, analytics, commerce, and realtime tables may still exist in historical schemas. They are not part of the active catch-up runtime.
