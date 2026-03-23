# Database Integration Guide

How to connect to and query the sports database from external services.

## Connection

```python
# Async (FastAPI, asyncio)
DATABASE_URL = "postgresql+asyncpg://user:pass@host:5432/sports"

# Sync (scripts, pandas, Celery)
DATABASE_URL = "postgresql+psycopg://user:pass@host:5432/sports"
```

## Schema Overview

### Core Sports Data

| Table | Description |
|-------|-------------|
| `sports_leagues` | League definitions (NBA, NHL, NCAAB, MLB, NFL) |
| `sports_teams` | Teams with names, abbreviations, colors, X handles, `external_codes` |
| `sports_players` | Player records linked to teams |
| `sports_games` | Games with scores, dates, status lifecycle, social scrape timestamps |
| `sports_team_boxscores` | Team-level stats per game (JSONB `raw_stats_json`) |
| `sports_player_boxscores` | Player-level stats per game (JSONB `raw_stats_json`) |
| `sports_game_plays` | Play-by-play events with period, clock, scores, play type |

### MLB Advanced Stats

| Table | Description |
|-------|-------------|
| `mlb_game_advanced_stats` | Statcast-derived team-level advanced batting stats (2 rows per game: home + away) |
| `mlb_player_advanced_stats` | Statcast-derived player-level advanced batting stats (one row per batter per game) |
| `mlb_pitcher_game_stats` | Per-game pitching stats (IP, K, BB, ERA, pitch count, etc.) linked to `sports_games` |
| `mlb_player_fielding_stats` | Per-game fielding stats (errors, assists, putouts, position) per player per game, from boxscore data |

### Odds & FairBet

| Table | Description |
|-------|-------------|
| `sports_game_odds` | Game-centric historical odds (opening + closing lines per book/market/side) |
| `fairbet_game_odds_work` | Bet-centric work table for cross-book comparison and EV computation |
| `closing_lines` | Durable closing-line snapshots captured when games go LIVE (baseline for CLV tracking) |

### Social Media

| Table | Description |
|-------|-------------|
| `team_social_posts` | X/Twitter posts per team, mapped to games via `mapping_status` and `game_id` |
| `team_social_accounts` | Team social media accounts (X handles, metadata) |
| `social_account_polls` | Tracks when each account was last polled (prevents redundant scraping) |

### Game Flow & Timeline

| Table | Description |
|-------|-------------|
| `sports_game_stories` | Generated game flow narratives (block-based, AI-generated) |
| `sports_game_timeline_artifacts` | Timeline artifacts combining PBP + social + odds events |
| `sports_game_pipeline_runs` | Pipeline execution tracking (per-game, per-run) |
| `sports_game_pipeline_stages` | Individual stage execution within a pipeline run |
| `bulk_story_generation_jobs` | Tracks bulk flow generation jobs |
| `sports_pbp_snapshots` | PBP data at different processing stages (for debugging/comparison) |
| `sports_entity_resolutions` | Entity resolution tracking for PBP data |

### Operations & Monitoring

| Table | Description |
|-------|-------------|
| `sports_scrape_runs` | Top-level scrape run audit log (ingestion runs) |
| `sports_job_runs` | Phase-level job tracking (odds, ingest, pbp, social, etc.) |
| `sports_game_conflicts` | Duplicate/ambiguous game identity tracking |
| `sports_missing_pbp` | Flags games missing required play-by-play data |

### Golf (DataGolf)

| Table | Description |
|-------|-------------|
| `golf_players` | Player catalog with DataGolf `dg_id`, name, country, DFS site IDs |
| `golf_tournaments` | Tournament definitions — event_id, tour, course, dates, purse, status |
| `golf_tournament_fields` | Entry lists per tournament — tee times, DFS salaries, status |
| `golf_leaderboard` | Live/final leaderboard — position, total score, per-round scores (r1-r4), SG, probabilities |
| `golf_rounds` | Per-player round data — scoring, SG splits, traditional stats |
| `golf_player_stats` | Skill ratings and rankings — periodic snapshots (current, long-term) |
| `golf_tournament_odds` | Outright odds — win/T5/T10/MC per player per sportsbook |
| `golf_dfs_projections` | DFS salary and projection snapshots per site/slate |

### Golf Pools

| Table | Description |
|-------|-------------|
| `golf_pools` | Pool definitions — club code, tournament FK, rules (JSONB), deadlines, status |
| `golf_pool_buckets` | Bucket definitions for Crestmont-style pools |
| `golf_pool_bucket_players` | Player assignments per bucket |
| `golf_pool_entries` | Submitted entries — email, picks, source, status |
| `golf_pool_entry_picks` | Individual golfer picks per entry |
| `golf_pool_entry_score_players` | Materialized per-golfer scoring (counted/dropped, round snapshots) |
| `golf_pool_entry_scores` | Materialized entry totals — aggregate score, rank, qualification status |
| `golf_pool_score_runs` | Scoring run audit trail |

### Analytics & ML

| Table | Description |
|-------|-------------|
| `analytics_feature_configs` | Feature loadouts — named sets of features with enabled/weight per sport/model_type |
| `analytics_training_jobs` | ML training job tracking (status, metrics, artifact path, Celery task ID) |
| `analytics_backtest_jobs` | Model backtest execution and results |
| `analytics_batch_sim_jobs` | Batch Monte Carlo simulation jobs |
| `analytics_prediction_outcomes` | Prediction vs actual outcome tracking for calibration. Includes sim observability columns: `sim_wp_std_dev`, `sim_iterations`, `sim_score_std_home/away`, `profile_games_home/away`, `sim_probability_source`, `feature_snapshot` (JSONB) |
| `analytics_degradation_alerts` | Model quality degradation alerts |
| `analytics_experiment_suites` | A/B experiment suites — groups of strategy variants to compare |
| `analytics_experiment_variants` | Individual variants within an experiment suite (strategy config, metrics) |
| `analytics_replay_jobs` | Historical replay jobs — re-simulate past games with different strategies |

### Authentication

| Table | Description |
|-------|-------------|
| `users` | User accounts — email (unique, indexed), password_hash, role (user/admin), is_active, created_at |

### Other

| Table | Description |
|-------|-------------|
| `user_preferences` | User preferences — synced settings, pins, revealed scores (JSONB) |
| `game_reading_positions` | User reading position tracking (resume point per game) |
| `openai_response_cache` | Cached OpenAI API responses for pipeline stages |

## Python Examples

### Direct SQL

```python
from sqlalchemy import create_engine, text

engine = create_engine("postgresql+psycopg://user:pass@host:5432/sports")

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT g.game_date, ht.name as home, at.name as away, g.home_score, g.away_score
        FROM sports_games g
        JOIN sports_teams ht ON g.home_team_id = ht.id
        JOIN sports_teams at ON g.away_team_id = at.id
        JOIN sports_leagues l ON g.league_id = l.id
        WHERE l.code = 'NBA' AND g.season = 2024
        ORDER BY g.game_date DESC
        LIMIT 10
    """))
    for row in result:
        print(row)
```

### Pandas

```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine("postgresql+psycopg://user:pass@host:5432/sports")

df = pd.read_sql("""
    SELECT g.game_date, l.code as league, g.home_score, g.away_score,
           tb.raw_stats_json->>'pts' as home_pts
    FROM sports_games g
    JOIN sports_leagues l ON g.league_id = l.id
    LEFT JOIN sports_team_boxscores tb ON tb.game_id = g.id AND tb.is_home = true
    WHERE l.code = 'NBA' AND g.status = 'final'
""", engine)
```

### ORM Models

```python
import sys
sys.path.insert(0, "/path/to/sports-data-admin/api")

from app.db.sports import SportsGame, SportsTeam, SportsLeague
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

engine = create_engine("postgresql+psycopg://user:pass@host:5432/sports")
Session = sessionmaker(bind=engine)

with Session() as session:
    games = session.execute(
        select(SportsGame)
        .join(SportsLeague)
        .where(SportsLeague.code == "NCAAB")
        .limit(20)
    ).scalars().all()
```

## Common Queries

### Games with Complete Data

```sql
SELECT g.*, l.code as league
FROM sports_games g
JOIN sports_leagues l ON g.league_id = l.id
WHERE EXISTS (SELECT 1 FROM sports_team_boxscores WHERE game_id = g.id)
  AND EXISTS (SELECT 1 FROM sports_game_odds WHERE game_id = g.id)
  AND g.status = 'final';
```

### Team Stats

```sql
SELECT t.name, tb.is_home,
       tb.raw_stats_json->>'pts' as points,
       tb.raw_stats_json->>'fg_pct' as fg_pct,
       tb.raw_stats_json->>'trb' as rebounds
FROM sports_team_boxscores tb
JOIN sports_teams t ON tb.team_id = t.id
JOIN sports_games g ON tb.game_id = g.id
WHERE g.id = 1234;
```

### Closing Lines

```sql
SELECT g.game_date, ht.name as home, at.name as away,
       MAX(CASE WHEN o.market_type = 'spread' AND o.side = 'home' THEN o.line END) as spread,
       MAX(CASE WHEN o.market_type = 'total' AND o.side = 'over' THEN o.line END) as total
FROM sports_games g
JOIN sports_teams ht ON g.home_team_id = ht.id
JOIN sports_teams at ON g.away_team_id = at.id
JOIN sports_game_odds o ON o.game_id = g.id
WHERE o.is_closing_line = true AND g.season = 2024
GROUP BY g.id, g.game_date, ht.name, at.name;
```

### Data Coverage

```sql
SELECT l.code, g.season, COUNT(*) as games,
       COUNT(DISTINCT tb.game_id) as with_boxscores,
       COUNT(DISTINCT o.game_id) as with_odds,
       COUNT(DISTINCT sp.game_id) as with_social
FROM sports_games g
JOIN sports_leagues l ON g.league_id = l.id
LEFT JOIN sports_team_boxscores tb ON tb.game_id = g.id
LEFT JOIN sports_game_odds o ON o.game_id = g.id
LEFT JOIN team_social_posts sp ON sp.game_id = g.id AND sp.mapping_status = 'mapped'
GROUP BY l.code, g.season
ORDER BY l.code, g.season DESC;
```

## REST API

For frontend/external service integration, use the REST API:

```typescript
const API_BASE = "http://localhost:8000";

// List games
const games = await fetch(`${API_BASE}/api/admin/sports/games?league=NBA&season=2024`);

// Game detail
const detail = await fetch(`${API_BASE}/api/admin/sports/games/1234`);
```

## Dependencies

```txt
# Sync access
sqlalchemy>=2.0.0
psycopg[binary]>=3.2.0

# Async access
sqlalchemy>=2.0.0
asyncpg>=0.29.0

# Analytics
pandas>=2.0.0
```

## Read-Only User

```sql
CREATE USER sports_readonly WITH PASSWORD 'password';
GRANT CONNECT ON DATABASE sports TO sports_readonly;
GRANT USAGE ON SCHEMA public TO sports_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO sports_readonly;
```
