# Sports Data Admin API

> FastAPI backend for Sports Data Admin: centralized sports data hub.

**Base URL:** `/api/admin/sports`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Date & Time Convention](#date--time-convention)
3. [Quick Start](#quick-start)
4. [Reference Tables](#reference-tables)
5. [Health Check](#health-check)
6. [Games](#games)
7. [Game Flow](#game-flow)
8. [Timeline](#timeline)
9. [Teams](#teams)
10. [Scraper Runs](#scraper-runs)
11. [Game Flow Pipeline](#game-flow-pipeline)
12. [Diagnostics](#diagnostics)
13. [Jobs](#jobs)
14. [Task Control](#task-control)
15. [PBP Inspection](#pbp-inspection)
16. [Entity Resolution](#entity-resolution)
17. [Social](#social)
18. [FairBet](#fairbet)
19. [Analytics](#analytics)
20. [Simulator](#simulator)
21. [Realtime](#realtime)
22. [Reading Positions](#reading-positions)
23. [Response Models](#response-models)

---

## Authentication

Authentication is layered: the API key is the base requirement for all
endpoints (except `/auth/*` and `/healthz`), and JWT bearer tokens add
role-based access on top.

### 1. API Key (Required for all non-auth endpoints)

Every request (except `/auth/*` signup/login/reset/magic-link and `/healthz`) must
include the `X-API-Key` header. This applies to both admin UI routes
**and** downstream consumer routes:

```http
GET /api/sports/games HTTP/1.1
Host: sports-data-admin.dock108.ai
X-API-Key: your-api-key-here
```

### 2. JWT Bearer Token (Role-based access)

Some endpoints additionally require a JWT to determine the caller's role.
Downstream consuming applications obtain tokens from the `/auth` endpoints
and include them **alongside** the API key.

#### Sign Up

```http
POST /auth/signup
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword"
}
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "role": "user"
}
```

#### Log In

```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword"
}
```

Response: same as signup.

#### Using the Token

Include the JWT in the `Authorization` header **alongside** the API key.
Without a JWT, role-gated endpoints treat the caller as `guest`:

```http
GET /api/fairbet/odds HTTP/1.1
X-API-Key: your-api-key-here
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

#### Forgot Password

```http
POST /auth/forgot-password
Content-Type: application/json

{
  "email": "user@example.com"
}
```

Always returns `200` with `{"detail": "If that email is registered, a reset link has been sent."}` to avoid leaking whether the email exists. If the account exists, a reset email is sent with a link to `{FRONTEND_URL}/auth/reset-password?token=...` (30-minute expiry).

#### Reset Password

```http
POST /auth/reset-password
Content-Type: application/json

{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "new_password": "new-password-min-8-chars"
}
```

Returns `{"detail": "Password has been reset."}`. `400` if the token is invalid or expired.

#### Magic Link (Passwordless Login)

Request a magic-link email:

```http
POST /auth/magic-link
Content-Type: application/json

{
  "email": "user@example.com"
}
```

Always returns `200` with `{"detail": "If that email is registered, a sign-in link has been sent."}`. If the account exists, a login email is sent with a link to `{FRONTEND_URL}/auth/magic-link?token=...` (15-minute expiry).

Exchange the token for a JWT:

```http
POST /auth/magic-link/verify
Content-Type: application/json

{
  "token": "eyJhbGciOiJIUzI1NiIs..."
}
```

Response: same as login (returns `TokenResponse` with `access_token` and `role`). `400` if the token is invalid or expired.

#### Get Current Identity

```http
GET /auth/me
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

Guest response (no token):
```json
{ "id": null, "email": null, "role": "guest" }
```

Authenticated response:
```json
{ "id": 42, "email": "user@example.com", "role": "user" }
```

### Roles

| Role | Description | Access |
|------|-------------|--------|
| `guest` | No token provided | Games, settings, pregame FairBet |
| `user` | Authenticated beta user | Everything guest + full FairBet |
| `admin` | Developer access | Everything user + analytics, history |

### JWT Payload

```json
{
  "sub": "42",
  "role": "user",
  "exp": 1710000000
}
```

### Error Responses

| Status | Description |
|--------|-------------|
| `401 Unauthorized` | Missing/invalid API key or expired/invalid JWT |
| `403 Forbidden` | Valid token but insufficient role for the endpoint |

### Configuration

| Variable | Description |
|----------|-------------|
| `API_KEY` | API key for admin endpoints (min 32 chars in production) |
| `JWT_SECRET` | Secret key for signing JWTs (change in production) |
| `JWT_EXPIRE_MINUTES` | Token lifetime in minutes (default: 1440 = 24h) |
| `AUTH_ENABLED` | Set to `false` to bypass role checks (all requests get admin). Default: `true` |
| `SMTP_HOST` | SMTP server for transactional email (password reset, magic links). Gmail: `smtp.gmail.com`. Emails are logged when unset |
| `SMTP_USER` | SMTP username (Gmail: your email address) |
| `SMTP_PASSWORD` | SMTP password (Gmail: [app password](https://myaccount.google.com/apppasswords), requires 2FA) |
| `MAIL_FROM` | Sender address. Gmail requires this to match `SMTP_USER` |
| `FRONTEND_URL` | Base URL for email links (default: `http://localhost:3000`) |

Generate secrets: `openssl rand -hex 32`

### Self-Service Account Management

Authenticated users can manage their own account. All mutations require password confirmation.

#### Update Email

```http
PATCH /auth/me/email
Authorization: Bearer <token>
Content-Type: application/json

{
  "email": "new@example.com",
  "password": "current-password"
}
```

Returns `MeResponse` with updated email. `409` if email is already taken.

#### Change Password

```http
PATCH /auth/me/password
Authorization: Bearer <token>
Content-Type: application/json

{
  "current_password": "old-password",
  "new_password": "new-password-min-8-chars"
}
```

Returns `{"detail": "Password updated"}`. `403` if current password is wrong.

#### Delete Account

```http
DELETE /auth/me
Authorization: Bearer <token>
Content-Type: application/json

{
  "password": "current-password"
}
```

Returns `{"detail": "Account deleted"}`. Permanent — cannot be undone.

### Admin User Management

Admin-only endpoints for managing user accounts. Secured by API key (admin UI).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/users` | List all users |
| `POST` | `/api/admin/users` | Create user (email, password, role) |
| `PATCH` | `/api/admin/users/{id}/role` | Change role (`user` or `admin`) |
| `PATCH` | `/api/admin/users/{id}/active` | Enable/disable account |
| `PATCH` | `/api/admin/users/{id}/email` | Change email |
| `PATCH` | `/api/admin/users/{id}/password` | Reset password |
| `DELETE` | `/api/admin/users/{id}` | Delete user |

### Health Check Exception

The `/healthz` endpoint does not require authentication to support infrastructure monitoring.

### Request Correlation

Every response includes an `X-Request-ID` header for log correlation. If the client sends an `X-Request-ID` header, the same value is echoed back; otherwise the server generates a UUID. Use this ID when reporting issues to trace the request through server logs.

---

## Date & Time Convention

### Request Parameters

Date parameters use **Eastern Time (America/New_York)**.

This represents "game day" as fans understand it:
- A 10:00 PM ET game on January 22 is a **"January 22 game"**
- Even though it's January 23 in UTC

### Response Fields

All datetime fields in responses are **UTC (ISO 8601)**.

| Field | Format | Example |
|-------|--------|---------|
| `startDate` (request) | Eastern | `2026-01-22` |
| `gameDate` (response) | UTC | `2026-01-23T03:00:00Z` |
| `lastScrapedAt` (response) | UTC | `2026-01-23T05:30:00Z` |

---

## Quick Start

**List games for a date:**
```http
GET /api/admin/sports/games?startDate=2026-01-22&endDate=2026-01-22&league=NBA
```

**Get game details:**
```http
GET /api/admin/sports/games/123
```

**Get game flow:**
```http
GET /api/admin/sports/games/123/flow
```

### Supported Leagues

| League | Code | Data Available |
|--------|------|----------------|
| NBA | `NBA` | Boxscores, PBP, Social, Odds, Game Flow, Timelines |
| NHL | `NHL` | Boxscores, PBP, Social, Odds, Game Flow, Timelines |
| NCAAB | `NCAAB` | Boxscores, PBP, Social, Odds, Game Flow, Timelines |
| MLB | `MLB` | Boxscores, PBP, Social, Odds, Game Flow, Timelines, Advanced Stats |

---

## Reference Tables

Look up any valid filter value, enum, or config constant without digging into source code.

### Game Statuses

| Status | Description |
|--------|-------------|
| `scheduled` | Not yet started |
| `pregame` | Within pregame window of tip time |
| `live` | Game in progress |
| `final` | Game completed |
| `archived` | Data complete, flows generated, >7 days old |
| `postponed` | Game postponed |
| `canceled` | Game canceled |

**Lifecycle:** `scheduled` &rarr; `pregame` &rarr; `live` &rarr; `final` &rarr; `archived`

Source: `api/app/db/sports.py` &rarr; `GameStatus`

### Market Types (Mainline)

| API Key | Canonical Type |
|---------|---------------|
| `h2h` | Moneyline |
| `spreads` | Spread (point spread / puck line) |
| `totals` | Total (over/under) |

Source: `scraper/sports_scraper/odds/client.py` &rarr; `MARKET_TYPES`

### Market Categories

| Category | Description | Example Markets |
|----------|-------------|-----------------|
| `mainline` | Core game odds | h2h, spreads, totals |
| `player_prop` | Individual player performance | player_points, player_rebounds, etc. |
| `team_prop` | Team performance bets | team_totals |
| `alternate` | Alternate line variations | alternate_spreads, alternate_totals |
| `period` | Period/quarter-specific | Markets ending in `_h1`, `_q1`, etc. |
| `game_prop` | Other game props | Catch-all for unclassified markets |

Source: `scraper/sports_scraper/models/schemas.py` &rarr; `classify_market()`

### Prop Markets by Sport

**NBA / NCAAB:** `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_points_rebounds_assists`, `player_blocks`, `player_steals`, `team_totals`, `alternate_spreads`, `alternate_totals`

**NHL:** `player_points`, `player_goals`, `player_assists`, `player_shots_on_goal`, `player_total_saves`, `team_totals`, `alternate_spreads`, `alternate_totals`

Source: `scraper/sports_scraper/odds/client.py` &rarr; `PROP_MARKETS`

### Included Sportsbooks (13)

BetMGM, BetRivers, Caesars, DraftKings, FanDuel, Pinnacle, 888sport, William Hill, Betfair Exchange, Betfair Sportsbook, Ladbrokes, Paddy Power, William Hill (UK)

### Excluded Sportsbooks (4)

BetOnline.ag, Bovada, Kalshi, Polymarket

> **Note:** All books are still scraped and persisted; exclusion happens at query time for quality filtering.

Source: `api/app/services/ev_config.py` &rarr; `INCLUDED_BOOKS`, `EXCLUDED_BOOKS`

### EV Confidence Tiers

| Tier | Criteria | Typical Markets |
|------|----------|-----------------|
| `high` | Pinnacle reference, &ge;3 qualifying books, &le;1hr staleness | NBA/NHL mainlines |
| `medium` | Pinnacle reference, &ge;3 qualifying books, &le;30min staleness | NCAAB mainlines, team props |
| `low` | Pinnacle reference, &ge;3 qualifying books, &le;30min staleness | Player props, alternates |

NCAAB mainlines use `medium` (vs `high` for NBA/NHL) due to thinner market liquidity. Period and game prop categories are disabled (no EV computation).

Source: `api/app/services/ev_config.py` &rarr; `_STRATEGY_MAP`

### Game Phases (Social Context)

| Phase | Description |
|-------|-------------|
| `pregame` | Before game starts |
| `in_game` | During live play |
| `postgame` | After game ends |

---

## Health Check

### `GET /healthz`

```json
{ "status": "ok", "app": "ok", "db": "ok" }
```

---

## Games

**Base path:** `/api/admin/sports`

### `GET /games`

List games with filtering and pagination.

| Parameter | Type | Description |
|-----------|------|-------------|
| `league` | `string[]` | Filter by league codes (NBA, NHL, NCAAB, MLB) |
| `season` | `int` | Filter by season year |
| `team` | `string` | Filter by team name (partial match) |
| `startDate` | `date` | Games on or after (Eastern Time) |
| `endDate` | `date` | Games on or before (Eastern Time) |
| `missingBoxscore` | `bool` | Games without boxscores |
| `missingPlayerStats` | `bool` | Games without player stats |
| `missingOdds` | `bool` | Games without odds |
| `missingSocial` | `bool` | Games without social posts |
| `missingAny` | `bool` | Games missing any data type |
| `hasPbp` | `bool` | Only games with play-by-play data |
| `finalOnly` | `bool` | Only include games with final/completed/official status |
| `safe` | `bool` | Exclude games with conflicts or missing team mappings |
| `limit` | `int` | Max results (1-200, default 50) |
| `offset` | `int` | Pagination offset |

**Response:**
```json
{
  "games": [
    {
      "id": 123,
      "leagueCode": "NBA",
      "gameDate": "2026-01-23T03:00:00Z",
      "homeTeam": "Lakers",
      "awayTeam": "Warriors",
      "homeScore": 112,
      "awayScore": 108,
      "hasBoxscore": true,
      "hasPlayerStats": true,
      "hasOdds": true,
      "hasSocial": true,
      "hasPbp": true,
      "hasFlow": true,
      "hasAdvancedStats": false,
      "playCount": 450,
      "socialPostCount": 12,
      "scrapeVersion": 2,
      "lastScrapedAt": "2026-01-23T05:00:00Z",
      "lastIngestedAt": "2026-01-23T05:00:00Z",
      "lastPbpAt": "2026-01-23T05:00:00Z",
      "lastSocialAt": "2026-01-23T04:00:00Z",
      "lastOddsAt": "2026-01-23T05:00:00Z",
      "lastAdvancedStatsAt": null,
      "homeTeamAbbr": "LAL",
      "awayTeamAbbr": "GSW",
      "homeTeamColorLight": "#FDB927",
      "homeTeamColorDark": "#552583",
      "awayTeamColorLight": "#006BB6",
      "awayTeamColorDark": "#FDB927"
    }
  ],
  "total": 245,
  "nextOffset": 50,
  "withBoxscoreCount": 240,
  "withPlayerStatsCount": 238,
  "withOddsCount": 245,
  "withSocialCount": 200,
  "withPbpCount": 230,
  "withFlowCount": 180,
  "withAdvancedStatsCount": 42
}
```

### `GET /games/{gameId}`

Full game detail including stats, odds, social posts, and plays.

**Response:**
```json
{
  "game": {
    "id": 123,
    "leagueCode": "NBA",
    "season": 2026,
    "seasonType": "regular",
    "gameDate": "2026-01-23T03:00:00Z",
    "homeTeam": "Lakers",
    "awayTeam": "Warriors",
    "homeScore": 112,
    "awayScore": 108,
    "status": "final",
    "hasBoxscore": true,
    "hasPlayerStats": true,
    "hasOdds": true,
    "hasSocial": true,
    "hasPbp": true,
    "hasFlow": true,
    "hasAdvancedStats": false,
    "playCount": 450,
    "socialPostCount": 12,
    "homeTeamXHandle": "@Lakers",
    "awayTeamXHandle": "@warriors",
    "homeTeamAbbr": "LAL",
    "awayTeamAbbr": "GSW",
    "homeTeamColorLight": "#FDB927",
    "homeTeamColorDark": "#552583",
    "awayTeamColorLight": "#006BB6",
    "awayTeamColorDark": "#FDB927"
  },
  "teamStats": [TeamStat, ...],
  "playerStats": [PlayerStat, ...],
  "nhlSkaters": [NHLSkaterStat, ...] | null,
  "nhlGoalies": [NHLGoalieStat, ...] | null,
  "mlbBatters": [MLBBatterStat, ...] | null,
  "mlbPitchers": [MLBPitcherStat, ...] | null,
  "mlbAdvancedStats": [MLBAdvancedTeamStats, ...] | null,
  "mlbAdvancedPlayerStats": [MLBAdvancedPlayerStats, ...] | null,
  "odds": [OddsEntry, ...],
  "socialPosts": [SocialPostEntry, ...],
  "plays": [PlayEntry, ...],
  "groupedPlays": [TieredPlayGroup, ...],
  "derivedMetrics": {...},
  "rawPayloads": {...},
  "dataHealth": NHLDataHealth | null,
  "oddsTable": [OddsTableGroup, ...] | null,
  "statAnnotations": [StatAnnotation, ...] | null
}
```

### `POST /games/{gameId}/rescrape`

Trigger rescrape for a game.

**Response:**
```json
{
  "runId": 456,
  "jobId": "abc-123",
  "message": "Job enqueued"
}
```

### `POST /games/{gameId}/resync-odds`

Resync odds for a game.

### `GET /games/{gameId}/preview-score`

Get a preview score for an upcoming game with excitement and quality ratings.

**Response:**
```json
{
  "gameId": "123",
  "excitementScore": 82,
  "qualityScore": 75,
  "tags": ["rivalry", "playoff_implications"],
  "nugget": "First meeting since the trade deadline blockbuster."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `gameId` | `string` | Game identifier |
| `excitementScore` | `int` | 0-100 excitement rating |
| `qualityScore` | `int` | 0-100 quality rating |
| `tags` | `string[]` | Descriptive tags |
| `nugget` | `string` | Short text nugget |

---

## Game Flow

### `GET /games/{gameId}/flow`

Get the AI-generated game flow for a game.

**Response:**
```json
{
  "gameId": 123,
  "homeTeam": "Lakers",
  "awayTeam": "Suns",
  "homeTeamAbbr": "LAL",
  "awayTeamAbbr": "PHX",
  "homeTeamColorLight": "#FDB927",
  "homeTeamColorDark": "#552583",
  "awayTeamColorLight": "#E56020",
  "awayTeamColorDark": "#1D1160",
  "leagueCode": "NBA",
  "flow": {
    "blocks": [
      {
        "blockIndex": 0,
        "role": "SETUP",
        "momentIndices": [0, 1, 2],
        "scoreBefore": [0, 0],
        "scoreAfter": [15, 12],
        "narrative": "The Suns jumped out early, with Durant draining two three-pointers in the opening minutes to set the tone."
      },
      {
        "blockIndex": 1,
        "role": "MOMENTUM_SHIFT",
        "momentIndices": [3, 4, 5],
        "scoreBefore": [15, 12],
        "scoreAfter": [28, 32],
        "narrative": "The Lakers responded with a 20-13 run spanning the late first and early second quarter, taking their first lead on a Davis alley-oop."
      }
    ],
    "moments": [
      {
        "playIds": [1, 2, 3],
        "explicitlyNarratedPlayIds": [2],
        "period": 1,
        "startClock": "11:42",
        "endClock": "11:00",
        "scoreBefore": [0, 0],
        "scoreAfter": [3, 0]
      }
    ]
  },
  "plays": [
    {
      "playId": 1,
      "playIndex": 1,
      "period": 1,
      "clock": "11:42",
      "playType": "3pt",
      "description": "K. Durant makes 3-pt shot from 24 ft",
      "homeScore": 0,
      "awayScore": 3
    }
  ],
  "validationPassed": true,
  "validationErrors": []
}
```

**Key Notes:**
- **Blocks are the primary output** — Use `blocks` for consumer-facing game summaries (3-7 blocks, 60-90 second read time)
- **Moments are for traceability** — Use `moments` to link narratives back to specific plays
- Each block has a semantic `role`: SETUP, MOMENTUM_SHIFT, RESPONSE, DECISION_POINT, or RESOLUTION
- `scoreBefore`/`scoreAfter` arrays are `[awayScore, homeScore]`
- `playId` equals `playIndex` (sequential play number)
- **Team colors are clash-resolved** — When home and away light-mode colors are too similar (Euclidean RGB distance < 0.12), the home team's colors are replaced with neutral black (`#000000`) / white (`#FFFFFF`). Consumers get ready-to-use colors with no client-side clash logic needed.

**Response (404):** No game flow exists for this game.

### Game Flow Structure

Game flows are AI-generated narrative summaries built from play-by-play data. Each game flow contains 3-7 **blocks** — short narratives (1-5 sentences each, ~65 words) designed for 60-90 second total read time.

**Blocks** are the consumer-facing output:
- Each block has a semantic role (SETUP, MOMENTUM_SHIFT, RESPONSE, DECISION_POINT, RESOLUTION)
- First block is always SETUP, last block is always RESOLUTION
- Total word count ≤ 600 words

**Moments** remain for internal traceability:
- Link blocks back to specific plays
- 15-25 moments per game (more granular than blocks)
- No consumer-facing narrative text

---

## Timeline

### `GET /games/{gameId}/timeline`

Retrieve a persisted timeline artifact for a game.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeline_version` | `string` | `v1` | Timeline version to retrieve |

**Response (200):** `TimelineArtifactResponse` (see [Response Models](#response-models))

**Response (404):** No timeline artifact exists for this game.

### `POST /games/{gameId}/timeline/generate`

Generate and persist a timeline artifact for a finalized game. Merges PBP, social, and odds events into a unified chronological timeline.

**Response (200):** `TimelineArtifactResponse`

**Response (409):** Game is not final.

**Response (422):** Missing PBP data or validation failed.

### `POST /timelines/generate/{gameId}`

Legacy alias for `POST /games/{gameId}/timeline/generate`.

### `GET /timelines/missing`

Games with PBP but no timeline.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `league_code` | `string` | Yes | NBA, NHL, NCAAB |
| `days_back` | `int` | No | Days to look back (default 7) |

### `POST /timelines/generate-batch`

Generate timelines for multiple games.

**Request:**
```json
{
  "game_ids": [123, 124, 125]
}
```

### `GET /timelines/existing`

Games with timeline artifacts.

### `POST /timelines/regenerate-batch`

Regenerate existing timelines.

---

## Teams

### `GET /teams`

List teams with game counts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | — | Filter by league code (NBA, NHL, NCAAB, MLB) |
| `search` | `string` | — | Search by team name, short name, or abbreviation (partial match) |
| `limit` | `int` | 100 | Max results (1-500) |
| `offset` | `int` | 0 | Pagination offset |

**Response:**
```json
{
  "teams": [
    {
      "id": 1,
      "name": "Los Angeles Lakers",
      "shortName": "Lakers",
      "abbreviation": "LAL",
      "leagueCode": "NBA",
      "gamesCount": 45,
      "colorLightHex": "#FDB927",
      "colorDarkHex": "#552583"
    }
  ],
  "total": 30
}
```

### `GET /teams/{teamId}`

Team detail with recent games.

### `PATCH /teams/{teamId}/colors`

Update team colors (light and dark hex values).

**Request:**
```json
{
  "colorLightHex": "#FDB927",
  "colorDarkHex": "#552583"
}
```

**Response:** `TeamDetail` with updated color fields.

### `GET /teams/{teamId}/social`

Team social media info.

---

## Scraper Runs

### `POST /scraper/runs`

Create scrape job.

**Request:**
```json
{
  "config": {
    "leagueCode": "NBA",
    "startDate": "2026-01-22",
    "endDate": "2026-01-22",
    "boxscores": true,
    "odds": true,
    "social": false,
    "pbp": false
  }
}
```

### `GET /scraper/runs`

List scrape runs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | — | Filter by league code |
| `status` | `string` | — | Filter by status: `pending`, `running`, `completed`, `error` |
| `limit` | `int` | 50 | Max results (1-200) |

### `GET /scraper/runs/{runId}`

Get run details.

### `POST /scraper/runs/{runId}/cancel`

Cancel pending job.

### `GET /logs`

Stream recent logs from a Docker container.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lines` | `int` | 1000 | Number of recent log lines to return (1-10,000) |

### `POST /scraper/cache/clear`

Clear cached scraper data for a league.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | required | League code (e.g., NBA, NHL) |
| `days` | `int` | 7 | Days of cache to clear (1-30) |

---

## Game Flow Pipeline

**Base path:** `/api/admin/sports/pipeline`

### `POST /runs`

Start a new pipeline run for a game.

**Request:**
```json
{
  "game_id": 123,
  "auto_chain": true
}
```

**Response:**
```json
{
  "run_id": 456,
  "run_uuid": "abc-123-def",
  "status": "pending",
  "message": "Pipeline run created"
}
```

### `GET /runs/{runId}`

Get pipeline run status.

**Response:**
```json
{
  "run_id": 456,
  "run_uuid": "abc-123-def",
  "game_id": 123,
  "status": "running",
  "current_stage": "GENERATE_MOMENTS",
  "stages": [...],
  "stages_completed": 2,
  "stages_total": 8,
  "progress_percent": 33
}
```

### `POST /runs/{runId}/advance`

Advance to the next stage (when not using auto_chain).

### `POST /batch`

Run pipeline for multiple games.

### `GET /stages`

Get pipeline stage definitions.

### `POST /bulk-generate-async`

Start bulk game flow generation.

**Request:**
```json
{
  "start_date": "2026-01-15",
  "end_date": "2026-01-20",
  "leagues": ["NBA", "NHL"],
  "force": false
}
```

### `GET /bulk-generate-status/{jobId}`

Get bulk generation job progress.

---

## Diagnostics

**Base path:** `/api/admin/sports`

### `GET /missing-pbp`

Games missing play-by-play.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | — | Filter by league code |
| `limit` | `int` | 100 | Max results (1-500) |

### `GET /conflicts`

Unresolved game conflicts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | — | Filter by league code |
| `limit` | `int` | 100 | Max results (1-500) |

---

## Jobs

### `GET /jobs`

List job runs.

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | `int` | Max results (1-200, default 50) |
| `phase` | `string` | Filter: `timeline_generation`, `flow_generation` |

---

## Task Control

**Base path:** `/api/admin`

On-demand dispatch of registered Celery tasks. Used by the Control Panel admin page.

### `GET /tasks/registry`

List all tasks available for manual dispatch.

**Response:**
```json
[
  {
    "name": "sync_mainline_odds",
    "queue": "sports-scraper",
    "description": "Sync mainline odds (spreads, totals, moneyline)"
  }
]
```

22 tasks are registered across categories: Ingestion, Polling, Odds, Social, Flows, Timelines, MLB Advanced Stats, Live Orchestration, and Utility. Each task specifies which Celery queue it routes to (`sports-scraper`, `social-scraper`, or `social-bulk`).

### `POST /tasks/trigger`

Dispatch a registered Celery task by name.

**Request:**
```json
{
  "task_name": "sync_mainline_odds",
  "args": ["NBA"]
}
```

**Response:**
```json
{
  "status": "dispatched",
  "task_name": "sync_mainline_odds",
  "task_id": "abc-123-def"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `task_name` | `string` | Must match a name from `GET /tasks/registry` |
| `args` | `array` | Positional arguments passed to the Celery task (optional, default `[]`) |

**Error (400):** Unknown task name.

---

## PBP Inspection

**Base path:** `/api/admin/sports/pbp`

### `GET /pbp/game/{gameId}`

Get current PBP for a game.

### `GET /pbp/game/{gameId}/detail`

Get detailed PBP including raw data.

### `GET /pbp/game/{gameId}/play/{playIndex}`

Get a single play by index.

### `GET /pbp/game/{gameId}/snapshots`

List all PBP snapshots for a game.

### `GET /pbp/snapshot/{snapshotId}`

Get full snapshot details.

### `GET /pbp/game/{gameId}/compare`

Compare current PBP with a snapshot.

### `GET /pbp/game/{gameId}/resolution-issues`

List plays with resolution issues.

---

## Entity Resolution

**Base path:** `/api/admin/sports/resolution`

### `GET /resolution/game/{gameId}`

Get entity resolution summary.

### `GET /resolution/game/{gameId}/live`

Analyze current PBP for resolution issues.

### `GET /resolution/pipeline-run/{runId}`

Get resolution summary for a pipeline run.

### `GET /resolution/issues`

List games with resolution issues.

---

## Social

**Base path:** `/api/social`

### `GET /posts`

List social posts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `game_id` | `int` | — | Filter by game |
| `team_id` | `string` | — | Filter by team abbreviation (e.g., "GSW") |
| `start_date` | `datetime` | — | Filter by posted_at &ge; value (ISO 8601) |
| `end_date` | `datetime` | — | Filter by posted_at &le; value (ISO 8601) |
| `limit` | `int` | 100 | Max results (1-500) |
| `offset` | `int` | 0 | Pagination offset |

### `GET /posts/game/{gameId}`

Posts for a game.

### `POST /posts`

Create post.

### `POST /posts/bulk`

Bulk create posts.

### `DELETE /posts/{postId}`

Delete post.

### `GET /accounts`

List social accounts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | — | Filter by league code |
| `team_id` | `int` | — | Filter by team ID |
| `platform` | `string` | — | Filter by platform (e.g., "x") |
| `limit` | `int` | 100 | Max results (1-500) |
| `offset` | `int` | 0 | Pagination offset |

### `POST /accounts`

Create/update account.

---

## FairBet

**Base path:** `/api/fairbet`

Odds comparison tool with expected value (EV) analysis across multiple sportsbooks. Displays cross-book betting lines with fair odds computation using Pinnacle as the sharp reference.

> **Deep Dive:** See [Odds & FairBet Pipeline](ingestion/odds-and-fairbet.md) for the full data flow from ingestion through game matching, selection key generation, and EV computation.

### Supported Leagues

- NBA
- NHL
- NCAAB
- MLB

### `GET /odds`

Get bet-centric odds for cross-book comparison with EV annotations.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `league` | `string` | — | Filter by league code (NBA, NHL, NCAAB, MLB) |
| `market_category` | `string` | — | Filter by market category (see [Market Categories](#market-categories)) |
| `game_id` | `int` | — | Filter to a specific game |
| `book` | `string` | — | Filter to a specific sportsbook |
| `player_name` | `string` | — | Filter by player name (partial match, case-insensitive) |
| `min_ev` | `float` | — | Minimum EV% threshold |
| `has_fair` | `bool` | — | Filter to bets with (`true`) or without (`false`) fair odds |
| `sort_by` | `string` | `ev` | Sort order: `ev`, `game_time`, `market` |
| `limit` | `int` | 100 | Max results (1-500) |
| `offset` | `int` | 0 | Pagination offset |

> **Note:** Only includes pregame games (future start time). Excluded books (see [Reference Tables](#excluded-sportsbooks-20)) are filtered out automatically at query time.

**Response:**
```json
{
  "bets": [
    {
      "game_id": 123,
      "league_code": "NBA",
      "home_team": "Los Angeles Lakers",
      "away_team": "Boston Celtics",
      "game_date": "2026-01-31T19:00:00Z",
      "market_key": "spreads",
      "selection_key": "team:los_angeles_lakers",
      "line_value": -3.5,
      "market_category": "mainline",
      "player_name": null,
      "description": null,
      "true_prob": 0.5432,
      "reference_price": -118,
      "opposite_reference_price": 108,
      "ev_confidence_tier": "high",
      "ev_disabled_reason": null,
      "ev_method": "pinnacle_devig",
      "has_fair": true,
      "fair_american_odds": -119,
      "selection_display": "LAL -3.5",
      "market_display_name": "Spread",
      "best_book": "DraftKings",
      "best_ev_percent": 2.15,
      "confidence_display_label": "Sharp",
      "ev_method_display_name": "Pinnacle Devig",
      "ev_method_explanation": "Fair odds derived by removing vig from Pinnacle's line using Shin's method.",
      "explanation_steps": [
        {
          "step_number": 1,
          "title": "Convert odds to implied probability",
          "description": "Each side's American odds are converted to an implied win probability.",
          "detail_rows": [
            { "label": "This side", "value": "-118 → 54.1%", "is_highlight": false },
            { "label": "Other side", "value": "+108 → 48.1%", "is_highlight": false },
            { "label": "Total", "value": "102.2%", "is_highlight": false }
          ]
        },
        {
          "step_number": 2,
          "title": "Identify the vig",
          "description": "The total implied probability exceeds 100% — the excess is the bookmaker's margin (vig).",
          "detail_rows": [
            { "label": "Total implied", "value": "102.2%", "is_highlight": false },
            { "label": "Should be", "value": "100.0%", "is_highlight": false },
            { "label": "Vig (margin)", "value": "2.2%", "is_highlight": true }
          ]
        },
        {
          "step_number": 3,
          "title": "Remove the vig (Shin's method)",
          "description": "Shin's method accounts for favorite-longshot bias, allocating more vig correction to longshots than favorites.",
          "detail_rows": [
            { "label": "Shin parameter (z)", "value": "0.0215", "is_highlight": false },
            { "label": "Formula", "value": "p = (√(z² + 4(1−z)q²) − z) / (2(1−z))", "is_highlight": false },
            { "label": "Fair probability", "value": "54.3%", "is_highlight": true },
            { "label": "Fair odds", "value": "-119", "is_highlight": false }
          ]
        },
        {
          "step_number": 4,
          "title": "Calculate EV at best price",
          "description": "Expected value measures the average profit per dollar wagered at the best available price.",
          "detail_rows": [
            { "label": "Best price", "value": "-110 (DraftKings)", "is_highlight": false },
            { "label": "Win", "value": "54.3% x $0.91 profit = +$0.4941", "is_highlight": false },
            { "label": "Loss", "value": "45.7% x $1.00 risked = -$0.4570", "is_highlight": false },
            { "label": "EV", "value": "+2.15%", "is_highlight": true }
          ]
        }
      ],
      "books": [
        {
          "book": "DraftKings",
          "price": -110,
          "observed_at": "2026-01-31T18:00:00Z",
          "ev_percent": 2.15,
          "implied_prob": 0.5238,
          "is_sharp": false,
          "ev_method": "pinnacle_devig",
          "ev_confidence_tier": "high",
          "book_abbr": "DK",
          "price_decimal": 1.909,
          "ev_tier": "positive"
        },
        {
          "book": "Pinnacle",
          "price": -118,
          "observed_at": "2026-01-31T18:00:00Z",
          "ev_percent": null,
          "implied_prob": 0.5414,
          "is_sharp": true,
          "ev_method": "pinnacle_devig",
          "ev_confidence_tier": "high",
          "book_abbr": "PIN",
          "price_decimal": 1.847,
          "ev_tier": "neutral"
        }
      ]
    }
  ],
  "total": 245,
  "books_available": ["BetMGM", "Caesars", "DraftKings", "FanDuel", "Pinnacle"],
  "market_categories_available": ["mainline", "player_prop", "team_prop"],
  "games_available": [
    {
      "game_id": 123,
      "matchup": "Boston Celtics @ Los Angeles Lakers",
      "game_date": "2026-01-31T19:00:00Z"
    }
  ],
  "ev_config": {
    "min_books_for_display": 3,
    "ev_color_thresholds": { "strong_positive": 5.0, "positive": 0.0 }
  }
}
```

**Field Notes:**
- `market_key`: `"h2h"` (moneyline), `"spreads"`, `"totals"`, or any prop market key (e.g., `"player_points"`)
- `selection_key`: `{entity_type}:{entity_slug}` — built from canonical DB team names, not Odds API names (e.g., `"team:los_angeles_lakers"`, `"player:lebron_james"`)
- `line_value`: Spread or total number; `0` for moneyline
- `true_prob`: Fair probability derived from Pinnacle devig (null if EV computation disabled)
- `ev_percent`: Expected value percentage vs fair odds (positive = +EV bet)
- `is_sharp`: `true` for the Pinnacle reference line
- `market_categories_available`: Dynamic list of categories with data for the current filter
- `games_available`: Dropdown-friendly list of pregame games with odds data
- `fair_american_odds`: Fair odds in American format derived from `true_prob`
- `selection_display`: Human-readable selection label (e.g., "LAL -3.5", "Over 215.5", "LeBron James Over 25.5")
- `market_display_name`: Human-readable market name (e.g., "Spread", "Player Points")
- `best_book`: Book with the highest EV% for this bet
- `best_ev_percent`: Highest EV% across all books
- `confidence_display_label`: Human-readable confidence tier ("Sharp", "Market", "Thin")
- `ev_method_display_name`: Human-readable EV method name (e.g., "Pinnacle Devig")
- `ev_method_explanation`: Sentence explaining how fair odds were derived
- `explanation_steps`: Step-by-step math walkthrough of how fair odds were derived. Each step has `step_number`, `title`, `description`, and `detail_rows` (label/value pairs with optional `is_highlight`). `null` when not enriched. Paths: Pinnacle devig (3-4 steps), extrapolated (3-4 steps), fallback (1-2 steps), not available (1 step with disabled reason label)
- `ev_config`: Global configuration for EV display thresholds
- Per-book `book_abbr`: Short abbreviation (e.g., "DK", "FD", "PIN")
- Per-book `price_decimal`: Decimal odds equivalent of the American price
- Per-book `ev_tier`: `"strong_positive"` (≥5%), `"positive"` (≥0%), `"negative"`, or `"neutral"` (sharp book)

### `POST /parlay/evaluate`

Evaluate a parlay by multiplying true probabilities. Returns combined fair probability and fair American odds.

**Request Body:**
```json
{
  "legs": [
    { "trueProb": 0.55, "confidence": 0.9 },
    { "trueProb": 0.60, "confidence": 0.85 }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `legs` | `array` | 2-20 legs, each with `trueProb` (0-1) and optional `confidence` (0-1) |

**Response:**
```json
{
  "fairProbability": 0.33,
  "fairAmericanOdds": 203,
  "combinedConfidence": 0.8746,
  "legCount": 2
}
```

| Field | Type | Description |
|-------|------|-------------|
| `fairProbability` | `float` | Product of all leg `trueProb` values |
| `fairAmericanOdds` | `int \| null` | Fair odds in American format |
| `combinedConfidence` | `float` | Geometric mean of leg confidences (1.0 if none provided) |
| `legCount` | `int` | Number of legs |

### `GET /live/games`

Discover all games that currently have live odds data in Redis. Returns a list of games with basic info (teams, date, status). Use this to populate game selectors or to drive the multi-game live odds page.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `league` | `string` | Filter by league code (`NBA`, `NHL`, `NCAAB`, `MLB`) |

**Response:**

```json
[
  {
    "game_id": 123,
    "league_code": "NBA",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "game_date": "2026-03-08T19:00:00Z",
    "status": "LIVE"
  }
]
```

Returns an empty array when no games have live odds in Redis. Games are sorted by `game_date`.

---

### `GET /live`

Compute +EV fair-bet odds for a live in-game event. Reads aggregated multi-book live odds from Redis, runs the same EV pipeline as pre-game (Shin devig, Pinnacle reference, extrapolation), and returns annotated bet definitions. Nothing is persisted to the DB.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `game_id` | `int` | **Required.** Game ID |
| `market_category` | `string` | Filter by market category (`mainline`, `player_prop`, `team_prop`, `alternate`) |
| `sort_by` | `string` | Sort order: `ev` (default), `market` |

**Response:**

```json
{
  "game_id": 123,
  "league_code": "NBA",
  "home_team": "Los Angeles Lakers",
  "away_team": "Boston Celtics",
  "bets": [
    {
      "game_id": 123,
      "league_code": "NBA",
      "home_team": "Los Angeles Lakers",
      "away_team": "Boston Celtics",
      "game_date": "2026-03-05T19:00:00Z",
      "market_key": "spreads",
      "selection_key": "team:los_angeles_lakers",
      "line_value": -3.5,
      "market_category": "mainline",
      "true_prob": 0.5432,
      "reference_price": -118,
      "ev_method": "pinnacle_devig",
      "has_fair": true,
      "fair_american_odds": -119,
      "selection_display": "LAL -3.5",
      "market_display_name": "Spread",
      "best_book": "DraftKings",
      "best_ev_percent": 2.15,
      "explanation_steps": ["..."],
      "books": [
        {
          "book": "DraftKings",
          "price": -110,
          "observed_at": "2026-03-05T19:30:00Z",
          "ev_percent": 2.15,
          "is_sharp": false,
          "book_abbr": "DK",
          "ev_tier": "positive"
        }
      ]
    }
  ],
  "total": 12,
  "books_available": ["DraftKings", "FanDuel", "Pinnacle"],
  "market_categories_available": ["mainline"],
  "last_updated_at": "2026-03-05T19:30:00+00:00",
  "ev_diagnostics": {
    "total_pairs": 6,
    "total_unpaired": 0,
    "passed": 5,
    "reference_missing": 1
  }
}
```

The `bets` array uses the same `BetDefinition` shape as the pre-game `/odds` endpoint, including all display enrichment fields (`fair_american_odds`, `selection_display`, `market_display_name`, `explanation_steps`, per-book `book_abbr`, `ev_tier`, etc.). See the `/odds` response documentation above for field semantics.

---

## Analytics

**Base path:** `/api/analytics`

Predictive modeling, simulation, and matchup analysis. See [Analytics](analytics.md) for the full engine architecture.

### Profiles & Matchups

#### `GET /team`

Get analytical profile for a team.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code (e.g., `mlb`) |
| `team_id` | `string` | Yes | Team identifier |

**Response:**
```json
{
  "sport": "mlb",
  "team_id": "NYY",
  "name": "New York Yankees",
  "metrics": { "contact_rate": 0.78, "power_index": 0.65, ... }
}
```

#### `GET /player`

Get analytical profile for a player.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code |
| `player_id` | `string` | Yes | Player identifier |

**Response:** Same shape as `/team` with `player_id` instead of `team_id`.

#### `GET /matchup`

Head-to-head matchup analysis between two entities.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code |
| `entity_a` | `string` | Yes | First entity (e.g., batter) |
| `entity_b` | `string` | Yes | Second entity (e.g., pitcher) |

**Response:**
```json
{
  "sport": "mlb",
  "entity_a": "batter_123",
  "entity_b": "pitcher_456",
  "probabilities": { "strikeout": 0.22, "walk": 0.08, "single": 0.18, ... },
  "comparison": { ... },
  "advantages": { ... }
}
```

### MLB Teams

#### `GET /mlb-teams`

List MLB teams with the number of games that have advanced Statcast data. Used by the simulator UI to populate team dropdowns.

**Response:**
```json
{
  "teams": [
    {
      "id": 1,
      "name": "New York Yankees",
      "short_name": "Yankees",
      "abbreviation": "NYY",
      "games_with_stats": 162
    }
  ],
  "count": 30
}
```

### MLB Roster

#### `GET /mlb-roster`

Get recent roster for an MLB team. Returns batters and pitchers who have appeared in games within the last 30 days, ordered by frequency. Used to populate lineup and pitcher selectors before running a lineup-aware simulation.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `team` | `string` | Yes | Team abbreviation (e.g., `NYY`) |

**Response:**
```json
{
  "batters": [
    { "external_ref": "660271", "name": "Aaron Judge", "games_played": 28 },
    { "external_ref": "592450", "name": "Juan Soto", "games_played": 27 }
  ],
  "pitchers": [
    { "external_ref": "543037", "name": "Gerrit Cole", "games": 6, "avg_ip": 6.2 },
    { "external_ref": "656302", "name": "Carlos Rodon", "games": 5, "avg_ip": 5.8 }
  ]
}
```

- **Batters:** From `MLBPlayerAdvancedStats`, ordered by game count descending
- **Pitchers:** From `SportsPlayerBoxscore` (where `innings_pitched > 0`), ordered by appearance count descending

### Simulation

#### `POST /simulate`

Run a full Monte Carlo simulation. Supports two modes:

1. **Team-level** (default): Uses aggregated team profiles. Omit lineup fields.
2. **Lineup-aware**: Pre-computes per-batter vs pitcher matchup probabilities for each spot in the batting order. Each batter gets individualized plate appearance distributions based on their rolling Statcast profile vs the opposing pitcher's tendencies. Provide all four lineup fields to activate.

**Lineup-aware request:**
```json
{
  "sport": "mlb",
  "home_team": "NYY",
  "away_team": "BOS",
  "iterations": 10000,
  "rolling_window": 30,
  "probability_mode": "ml",
  "home_lineup": [
    { "external_ref": "660271", "name": "Aaron Judge" },
    { "external_ref": "592450", "name": "Juan Soto" },
    { "external_ref": "596019", "name": "Anthony Rizzo" },
    { "external_ref": "650402", "name": "Giancarlo Stanton" },
    { "external_ref": "543685", "name": "DJ LeMahieu" },
    { "external_ref": "664056", "name": "Gleyber Torres" },
    { "external_ref": "666176", "name": "Anthony Volpe" },
    { "external_ref": "682928", "name": "Austin Wells" },
    { "external_ref": "665862", "name": "Trent Grisham" }
  ],
  "away_lineup": [
    { "external_ref": "646240", "name": "Rafael Devers" },
    { "external_ref": "665489", "name": "Jarren Duran" },
    { "external_ref": "680776", "name": "Masataka Yoshida" },
    { "external_ref": "596105", "name": "Trevor Story" },
    { "external_ref": "656555", "name": "Alex Verdugo" },
    { "external_ref": "680557", "name": "Triston Casas" },
    { "external_ref": "543807", "name": "Justin Turner" },
    { "external_ref": "663993", "name": "Connor Wong" },
    { "external_ref": "672284", "name": "Ceddanne Rafaela" }
  ],
  "home_starter": { "external_ref": "543037", "name": "Gerrit Cole" },
  "away_starter": { "external_ref": "678394", "name": "Brayan Bello" },
  "starter_innings": 6.0
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sport` | `string` | — | **Required.** Sport code (only `mlb` supported) |
| `home_team` | `string` | — | **Required.** Home team abbreviation |
| `away_team` | `string` | — | **Required.** Away team abbreviation |
| `iterations` | `int` | 5000 | Simulation count (100–50,000) |
| `rolling_window` | `int` | 30 | Recent games for profile building (5–162) |
| `seed` | `int?` | `null` | Deterministic seed for reproducibility |
| `probability_mode` | `string?` | `null` | `rule_based`, `ml`, `ensemble`, or `pitch_level` |
| `sportsbook` | `object?` | `null` | Sportsbook lines for EV comparison |
| `home_lineup` | `LineupSlot[9]?` | `null` | Home batting order (exactly 9 batters) |
| `away_lineup` | `LineupSlot[9]?` | `null` | Away batting order (exactly 9 batters) |
| `home_starter` | `PitcherSlot?` | `null` | Home starting pitcher |
| `away_starter` | `PitcherSlot?` | `null` | Away starting pitcher |
| `starter_innings` | `float` | 6.0 | Inning when bullpen takes over (4.0–9.0) |

**`LineupSlot` / `PitcherSlot` shape:**
```json
{ "external_ref": "660271", "name": "Aaron Judge" }
```
- `external_ref` — Player ID from the roster endpoint (required)
- `name` — Display name (optional, for logging only)

**Lineup mode activation:** Both `home_lineup` and `away_lineup` must be provided with exactly 9 entries each. If either is missing or has a different count, the simulation falls back to team-level mode silently.

**Pitcher transition model:** The starter's matchup weights are used through the inning specified by `starter_innings` (default 6). After that, bullpen weights (derived from the opposing team's aggregate pitching profile) take over. Pre-computation happens before the simulation loop: 9 batters × 2 pitcher states × 2 teams = 36 `batter_vs_pitcher()` calls, done once. The hot loop indexes into pre-computed arrays.

**Response:**
```json
{
  "sport": "mlb",
  "home_team": "NYY",
  "away_team": "BOS",
  "home_win_probability": 0.5432,
  "away_win_probability": 0.4568,
  "average_home_score": 4.8,
  "average_away_score": 4.2,
  "average_total": 9.0,
  "median_total": 9,
  "most_common_scores": [{ "score": "4-5", "probability": 0.042 }],
  "iterations": 10000,
  "profile_meta": {
    "has_profiles": true,
    "rolling_window": 30,
    "model_win_probability": 0.5821,
    "model_prediction_source": "game_model",
    "home_pa_source": "team_profile",
    "away_pa_source": "team_profile",
    "lineup_mode": {
      "enabled": true,
      "home_batters_resolved": 9,
      "away_batters_resolved": 9,
      "home_starter_resolved": true,
      "away_starter_resolved": true,
      "starter_innings": 6.0
    }
  },
  "model_home_win_probability": 0.5821,
  "home_pa_probabilities": {
    "strikeout_probability": 0.2315,
    "walk_probability": 0.0912,
    "single_probability": 0.1423,
    "double_probability": 0.0534,
    "triple_probability": 0.008,
    "home_run_probability": 0.0315
  },
  "away_pa_probabilities": { "..." : "..." }
}
```

#### `POST /live-simulate`

Simulate from a live game state (current inning, outs, bases, score).

**Request body:**
```json
{
  "sport": "mlb",
  "inning": 5,
  "half": "top",
  "outs": 1,
  "bases": { "first": true, "second": false, "third": false },
  "score": { "home": 3, "away": 2 },
  "iterations": 2000,
  "probability_mode": "rule_based"
}
```

### Prediction Outcomes & Calibration

#### `POST /record-outcomes`

Trigger auto-recording of outcomes for finalized games. Dispatches a Celery task that matches pending predictions against completed `SportsGame` records.

#### `GET /prediction-outcomes`

List prediction outcome records.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sport` | `string` | — | Filter by sport |
| `status` | `string` | — | `pending` or `resolved` |
| `limit` | `int` | 100 | Max results (1–500) |

#### `GET /calibration-report`

Aggregate calibration metrics from resolved prediction outcomes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sport` | `string` | — | Filter by sport |

**Response:**
```json
{
  "total_predictions": 150,
  "resolved": 150,
  "accuracy": 0.58,
  "brier_score": 0.21,
  "avg_home_score_error": 1.2,
  "avg_away_score_error": 1.1,
  "home_bias": 0.02
}
```

### Feature Loadouts (DB-Backed)

#### `GET /feature-configs`

List all feature loadouts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | No | Filter by sport |
| `model_type` | `string` | No | Filter by model type |

#### `GET /feature-config/{id}`

Get a feature loadout by ID.

#### `POST /feature-config`

Create a new feature loadout.

**Request body:**
```json
{
  "name": "mlb_pa_v2",
  "sport": "mlb",
  "model_type": "plate_appearance",
  "features": [
    { "name": "contact_rate", "enabled": true, "weight": 1.0 },
    { "name": "barrel_rate", "enabled": true, "weight": 1.2 }
  ],
  "is_default": false
}
```

#### `PUT /feature-config/{id}`

Update an existing feature loadout. All fields optional (partial update).

#### `DELETE /feature-config/{id}`

Delete a feature loadout by ID.

#### `POST /feature-config/{id}/clone`

Clone a feature loadout. Optional `name` query parameter for the clone's name.

#### `GET /available-features`

List all available features with descriptions and DB coverage.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | No | Sport (default: `mlb`) |

### Training Pipeline

#### `POST /train`

Start an async model training job via Celery.

**Request body:**
```json
{
  "feature_config_id": 1,
  "sport": "mlb",
  "model_type": "game",
  "algorithm": "gradient_boosting",
  "date_start": "2025-04-01",
  "date_end": "2025-10-01",
  "test_split": 0.2,
  "random_state": 42
}
```

#### `GET /training-jobs`

List training jobs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | No | Filter by sport |
| `status` | `string` | No | Filter by status (`pending`, `running`, `completed`, `failed`) |

#### `GET /training-job/{id}`

Get training job details by ID.

#### `POST /training-job/{id}/cancel`

Cancel a pending, queued, or running training job. Revokes the Celery task if it has been dispatched.

**Response:**
```json
{
  "status": "cancelled",
  "job_id": 5
}
```

### Model Inference

#### `POST /model-predict`

Generate a prediction using the active ML model.

**Request body:**
```json
{
  "sport": "mlb",
  "model_type": "plate_appearance",
  "profiles": { "batter": { "contact_rate": 0.8 }, "pitcher": { "strikeout_rate": 0.25 } },
  "config_name": null
}
```

**Response:**
```json
{
  "sport": "mlb",
  "model_type": "plate_appearance",
  "probabilities": { "strikeout": 0.22, "out": 0.46, "walk": 0.08, "single": 0.15, ... }
}
```

#### `GET /model-predict`

Sample prediction with empty profiles (useful for checking model availability).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code |
| `model_type` | `string` | Yes | Model type |

### Model Registry

#### `GET /models`

List registered models with filtering and sorting.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `sport` | `string` | — | Filter by sport |
| `model_type` | `string` | — | Filter by model type |
| `sort_by` | `string` | — | Sort key: `created_at`, `accuracy`, `log_loss`, `brier_score`, `version` |
| `sort_desc` | `bool` | `true` | Sort descending |
| `active_only` | `bool` | `false` | Only active models |

#### `GET /models/details`

Full details for a single model.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model_id` | `string` | Yes | Model ID |

#### `GET /models/compare`

Compare evaluation metrics across model versions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code |
| `model_type` | `string` | Yes | Model type |
| `model_ids` | `string` | Yes | Comma-separated model IDs |

#### `POST /models/activate`

Activate a registered model. Clears the inference cache.

**Request body:**
```json
{
  "sport": "mlb",
  "model_type": "plate_appearance",
  "model_id": "pa_model_v3"
}
```

#### `GET /models/active`

Get the currently active model for a sport + model type.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code |
| `model_type` | `string` | Yes | Model type |

#### `GET /model-metrics`

Get evaluation metrics for registered models.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_id` | `string` | — | Filter by model ID |
| `sport` | `string` | — | Filter by sport |
| `model_type` | `string` | — | Filter by model type |

### Ensemble Configuration

#### `GET /ensemble-config`

Get ensemble configuration for a sport + model type.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sport` | `string` | Yes | Sport code |
| `model_type` | `string` | Yes | Model type |

**Response:**
```json
{
  "sport": "mlb",
  "model_type": "plate_appearance",
  "providers": [
    { "name": "rule_based", "weight": 0.4 },
    { "name": "ml", "weight": 0.6 }
  ]
}
```

#### `GET /ensemble-configs`

List all ensemble configurations.

#### `POST /ensemble-config`

Update ensemble weights for a sport + model type.

**Request body:**
```json
{
  "sport": "mlb",
  "model_type": "plate_appearance",
  "providers": [
    { "name": "rule_based", "weight": 0.3 },
    { "name": "ml", "weight": 0.7 }
  ]
}
```

---

## Simulator

**Base path:** `/api/simulator`

Public-facing MLB game simulation endpoints for downstream apps. Uses ML models and real Statcast data. Probability mode is always `ml` — downstream consumers don't need to configure probability modes, ensemble weights, or feature loadouts.

> **For internal/admin simulation with full control** (probability modes, ensemble weights, custom probabilities, sportsbook comparison), use the [Analytics](#analytics) `POST /api/analytics/simulate` endpoint instead.

### Quick Start

```bash
# 1. List available teams
curl -H "X-API-Key: $API_KEY" \
  https://sports-data-admin.dock108.ai/api/simulator/mlb/teams

# 2. Run a simulation
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  https://sports-data-admin.dock108.ai/api/simulator/mlb \
  -d '{"home_team": "NYY", "away_team": "LAD"}'
```

### `GET /mlb/teams`

List MLB teams available for simulation. Use the `abbreviation` values as `home_team` / `away_team` in the simulation endpoint. Teams with more `games_with_stats` produce more accurate, data-driven simulations.

**Response:**
```json
{
  "teams": [
    {
      "abbreviation": "NYY",
      "name": "New York Yankees",
      "short_name": "Yankees",
      "games_with_stats": 162
    },
    {
      "abbreviation": "LAD",
      "name": "Los Angeles Dodgers",
      "short_name": "Dodgers",
      "games_with_stats": 158
    }
  ],
  "count": 30
}
```

| Field | Type | Description |
|-------|------|-------------|
| `abbreviation` | `string` | Team abbreviation — use this as `home_team` / `away_team` |
| `name` | `string` | Full team name |
| `short_name` | `string?` | Short name (e.g. "Yankees") |
| `games_with_stats` | `int` | Number of games with advanced Statcast data. Teams with 0 use league-average defaults. |

### `POST /mlb`

Run a Monte Carlo game simulation between two MLB teams.

**How it works:**

1. Loads each team's rolling statistical profile from real Statcast game data (barrel rate, whiff rate, contact rate, etc.)
2. Converts profiles into plate-appearance event probabilities (strikeout, walk, single, double, triple, home run)
3. Simulates the game plate-appearance by plate-appearance for the requested number of iterations
4. Aggregates results into win probabilities, expected scores, and most common final scores
5. If a trained game model is active, also runs a direct model prediction for an additional win probability estimate

**Request body:**

Only `home_team` and `away_team` are required. Everything else has sensible defaults.

```json
{
  "home_team": "NYY",
  "away_team": "LAD",
  "iterations": 5000,
  "rolling_window": 30,
  "seed": 42
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `home_team` | `string` | — | **Required.** Home team abbreviation (2–4 chars, e.g. `NYY`) |
| `away_team` | `string` | — | **Required.** Away team abbreviation (2–4 chars, e.g. `LAD`) |
| `iterations` | `int` | `5000` | Number of Monte Carlo iterations (100–50,000). Higher = more precise but slower. Recommended: 5,000 for quick results, 20,000+ for precision. |
| `rolling_window` | `int` | `30` | Number of recent games for building each team's profile (5–162). Smaller (10–15) reacts to hot/cold streaks; larger (40–80) is more stable. |
| `seed` | `int?` | `null` | Optional random seed for reproducible results. Same seed + inputs = identical output. |

**Response:**

```json
{
  "home_team": "NYY",
  "away_team": "LAD",
  "home_win_probability": 0.5432,
  "away_win_probability": 0.4568,
  "average_home_score": 4.8,
  "average_away_score": 4.2,
  "average_total": 9.0,
  "median_total": 9,
  "most_common_scores": [
    { "score": "4-5", "probability": 0.042 },
    { "score": "3-4", "probability": 0.038 }
  ],
  "iterations": 5000,
  "rolling_window": 30,
  "profiles_loaded": true,
  "home_pa_probabilities": {
    "strikeout": 0.2315,
    "walk": 0.0912,
    "single": 0.1423,
    "double": 0.0534,
    "triple": 0.008,
    "home_run": 0.0315
  },
  "away_pa_probabilities": {
    "strikeout": 0.2187,
    "walk": 0.0845,
    "single": 0.1512,
    "double": 0.0489,
    "triple": 0.008,
    "home_run": 0.0270
  },
  "model_home_win_probability": 0.5821
}
```

| Field | Type | Description |
|-------|------|-------------|
| `home_team` | `string` | Home team abbreviation |
| `away_team` | `string` | Away team abbreviation |
| `home_win_probability` | `float` | Probability the home team wins (0–1) |
| `away_win_probability` | `float` | Probability the away team wins (0–1) |
| `average_home_score` | `float` | Average home runs across all iterations |
| `average_away_score` | `float` | Average away runs across all iterations |
| `average_total` | `float` | Average combined total runs |
| `median_total` | `float` | Median combined total runs |
| `most_common_scores` | `array` | Top 10 most frequent final scores (score string + probability) |
| `iterations` | `int` | Number of iterations run |
| `rolling_window` | `int` | Rolling window used for profiles |
| `profiles_loaded` | `bool` | `true` if real team profiles were loaded. `false` means league-average defaults were used (team abbreviation not found or insufficient data). |
| `home_pa_probabilities` | `object?` | PA event probabilities used for the home team. `null` if profiles not loaded. |
| `away_pa_probabilities` | `object?` | PA event probabilities used for the away team. `null` if profiles not loaded. |
| `model_home_win_probability` | `float?` | Direct win probability from the trained game model, if one is active. `null` if no model available. This is separate from the Monte Carlo simulation — it's a single model inference. |

**PA probability keys:** `strikeout`, `walk`, `single`, `double`, `triple`, `home_run`

### Error Responses

| Status | Cause |
|--------|-------|
| `422` | Missing or invalid `home_team`/`away_team`, `iterations` out of range, etc. |
| `401` | Missing or invalid API key |

---

## Realtime

Live game updates via WebSocket or Server-Sent Events. Both transports deliver the same event envelope format.

### Channel Types

| Channel | Format | Description |
|---------|--------|-------------|
| Games list | `games:{league}:{date}` | Score/status patches for all games on a date |
| Game summary | `game:{gameId}:summary` | Single-game detail patch |
| Game PBP | `game:{gameId}:pbp` | Append-only play-by-play events |
| FairBet odds | `fairbet:odds` | Minimal FairBet odds change stream |

### `WS /v1/ws`

WebSocket endpoint for realtime subscriptions.

**Auth:** `X-API-Key` header or `api_key` query parameter.

**Subscribe:**
```json
{"action": "subscribe", "channels": ["games:NBA:2026-03-05", "game:123:summary"]}
```

**Unsubscribe:**
```json
{"action": "unsubscribe", "channels": ["game:123:summary"]}
```

### `GET /v1/sse`

Server-Sent Events endpoint. Same data as WS, alternative transport.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `channels` | `string` | **Required.** Comma-separated channel list |

**Auth:** `X-API-Key` header or `api_key` query parameter.

### `GET /v1/realtime/status`

Debug endpoint showing connected clients, channel subscriptions, and poller stats.

### Event Envelope

All events share this structure:

```json
{
  "type": "game_patch",
  "channel": "games:NBA:2026-03-05",
  "ts": 1741209600,
  "seq": 42,
  "boot_epoch": 1741200000,
  "gameId": 123,
  "patch": {}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | `game_patch`, `pbp_append`, or `fairbet_patch` |
| `channel` | `string` | Channel this event was published to |
| `ts` | `int` | Unix timestamp |
| `seq` | `int` | Monotonic sequence number per channel (for gap detection) |
| `boot_epoch` | `int` | Server boot timestamp (detect restarts → resubscribe) |

---

## Reading Positions

**Base path:** `/api`

### `POST /api/users/{userId}/games/{gameId}/reading-position`

Save reading position.

### `GET /api/users/{userId}/games/{gameId}/resume`

Get reading position.

---

## Response Models

All responses use **camelCase** field names.

### GameSummary

```typescript
interface GameSummary {
  id: number;
  leagueCode: string;
  gameDate: string;           // ISO 8601 UTC
  homeTeam: string;
  awayTeam: string;
  status: string | null;
  homeScore: number | null;
  awayScore: number | null;
  currentPeriod: number | null;
  gameClock: string | null;
  hasBoxscore: boolean;
  hasPlayerStats: boolean;
  hasOdds: boolean;
  hasSocial: boolean;
  hasPbp: boolean;
  hasFlow: boolean;
  hasAdvancedStats: boolean;   // MLB Statcast-derived advanced stats available
  playCount: number;
  socialPostCount: number;
  scrapeVersion: number | null;
  lastScrapedAt: string | null;
  lastIngestedAt: string | null;
  lastPbpAt: string | null;
  lastSocialAt: string | null;
  lastOddsAt: string | null;
  lastAdvancedStatsAt: string | null;  // MLB Statcast advanced stats timestamp
  derivedMetrics: Record<string, any> | null;  // Server-computed metrics (40+)
  homeTeamAbbr: string | null;       // Clash-resolved team abbreviation
  awayTeamAbbr: string | null;
  homeTeamColorLight: string | null;  // Clash-resolved hex color (light mode)
  homeTeamColorDark: string | null;   // Clash-resolved hex color (dark mode)
  awayTeamColorLight: string | null;
  awayTeamColorDark: string | null;
  // Status convenience flags
  isLive: boolean | null;              // Game currently in progress
  isFinal: boolean | null;             // Game completed (final/completed/official)
  isPregame: boolean | null;           // Game not yet started
  isTrulyCompleted: boolean | null;    // Final + has boxscore data
  readEligible: boolean | null;        // Game flow can be consumed
  currentPeriodLabel: string | null;   // "Q4", "2nd Half", "P3", "OT"
  liveSnapshot: LiveSnapshot | null;   // At-a-glance live state
  dateSection: string | null;          // "Today", "Yesterday", "Tomorrow", "Earlier", "Upcoming"
}

interface LiveSnapshot {
  periodLabel: string | null;   // "Q4", "2nd Half", "P3"
  timeLabel: string | null;     // "Q4 2:35", "2H 12:30"
  homeScore: number | null;
  awayScore: number | null;
  currentPeriod: number | null;
  gameClock: string | null;
}
```

### GameListResponse

```typescript
interface GameListResponse {
  games: GameSummary[];
  total: number;
  nextOffset: number | null;
  withBoxscoreCount: number;
  withPlayerStatsCount: number;
  withOddsCount: number;
  withSocialCount: number;
  withPbpCount: number;
  withFlowCount: number;
  withAdvancedStatsCount: number;  // MLB games with Statcast-derived advanced stats
}
```

### GameFlowResponse

```typescript
interface GameFlowResponse {
  gameId: number;
  flow: GameFlowContent;
  plays: GameFlowPlay[];
  validationPassed: boolean;
  validationErrors: string[];
  homeTeam: string | null;            // Team name
  awayTeam: string | null;
  homeTeamAbbr: string | null;        // Clash-resolved team abbreviation
  awayTeamAbbr: string | null;
  homeTeamColorLight: string | null;   // Clash-resolved hex color (light mode)
  homeTeamColorDark: string | null;    // Clash-resolved hex color (dark mode)
  awayTeamColorLight: string | null;
  awayTeamColorDark: string | null;
  leagueCode: string | null;
}

interface GameFlowContent {
  blocks: GameFlowBlock[];       // Consumer-facing narratives (3-7 per game)
  moments: GameFlowMoment[];     // Internal traceability (15-25 per game)
}

// Consumer-facing narrative block (1-5 sentences, ~65 words)
interface GameFlowBlock {
  blockIndex: number;         // Position (0-6)
  role: SemanticRole;         // SETUP, MOMENTUM_SHIFT, RESPONSE, DECISION_POINT, RESOLUTION
  momentIndices: number[];    // Which moments are grouped in this block
  periodStart: number;        // First period covered by this block
  periodEnd: number;          // Last period covered by this block
  scoreBefore: number[];      // [away, home]
  scoreAfter: number[];       // [away, home]
  playIds: number[];          // All play indices in this block
  keyPlayIds: number[];       // Highlighted plays
  narrative: string;          // 1-5 sentences (~65 words)
  miniBox: BlockMiniBox | null;  // Player stats for this segment
  embeddedSocialPostId?: number | null;  // Optional social post ID (max 1 per block, 5 per game)
  peak_margin?: number;       // Largest absolute margin within this block (omitted when 0)
  peak_leader?: number;       // 1=home led at peak, -1=away led at peak (omitted when 0)
}

type SemanticRole = "SETUP" | "MOMENTUM_SHIFT" | "RESPONSE" | "DECISION_POINT" | "RESOLUTION";

type GamePhase = "pregame" | "in_game" | "postgame";

// Internal traceability: links blocks to specific plays
interface GameFlowMoment {
  playIds: number[];
  explicitlyNarratedPlayIds: number[];
  period: number;
  startClock: string | null;
  endClock: string | null;
  scoreBefore: number[];      // [away, home]
  scoreAfter: number[];       // [away, home]
}

interface GameFlowPlay {
  playId: number;
  playIndex: number;
  period: number;
  clock: string | null;
  playType: string | null;
  description: string | null;
  homeScore: number | null;
  awayScore: number | null;
}
```

### SocialPostEntry

Social posts returned in the `socialPosts` array of `GET /games/{gameId}`. Sorted by total interactions (likes + retweets + replies) descending.

```typescript
interface SocialPostEntry {
  id: number;
  postUrl: string;
  postedAt: string;           // ISO 8601
  hasVideo: boolean;
  teamAbbreviation: string;
  tweetText: string | null;
  videoUrl: string | null;
  imageUrl: string | null;
  sourceHandle: string | null;
  mediaType: string | null;
  gamePhase: string | null;   // "pregame" | "in_game" | "postgame"
  likesCount: number | null;
  retweetsCount: number | null;
  repliesCount: number | null;
}
```

### TeamStat

Team-level boxscore stats. Two entries per game (home + away). The `stats` dict contains the raw JSONB from the data source — keys vary by league.

```typescript
interface TeamStat {
  team: string;
  isHome: boolean;
  stats: Record<string, any>;   // Raw JSONB — league-specific keys (see below)
  source: string | null;        // e.g. "nba_cdn", "cbb_api", "nhl_api"
  updatedAt: string | null;     // ISO 8601
  normalizedStats: NormalizedStat[] | null;  // Canonical stats with display labels (see below)
}

interface NormalizedStat {
  key: string;              // Canonical key (e.g. "points", "rebounds", "three_pointers_made")
  displayLabel: string;     // Display label (e.g. "PTS", "REB", "3PM")
  group: string;            // Stat group: "scoring", "shooting", "rebounds", "playmaking", "defense"
  value: number | string | null;
  formatType: string;       // "int", "float", "pct", "str"
}
```

`normalizedStats` resolves alias differences across data sources (Basketball Reference, NBA API, CBB API) into canonical keys with display labels. Clients can use these directly instead of maintaining their own alias tables.

#### NBA Team Stats JSONB (`stats` field)

Source: NBA CDN API (`cdn.nba.com`). All values are integers unless noted.

```json
{
  "points": 112,
  "rebounds": 45,
  "assists": 25,
  "turnovers": 14,
  "fg_made": 42,
  "fg_attempted": 88,
  "fg_pct": 0.477,
  "three_made": 12,
  "three_attempted": 35,
  "three_pct": 0.343,
  "ft_made": 16,
  "ft_attempted": 20,
  "ft_pct": 0.800,
  "offensive_rebounds": 10,
  "defensive_rebounds": 35,
  "steals": 8,
  "blocks": 5,
  "personal_fouls": 22,
  "team_fouls": 4,
  "technical_fouls": 1,
  "fast_break_points": 18,
  "points_in_paint": 48,
  "points_off_turnovers": 22,
  "second_chance_points": 12,
  "bench_points": 38,
  "biggest_lead": 15,
  "lead_changes": 12,
  "times_tied": 5
}
```

> **Note:** NBA team stats include all fields above. Older games may only contain `points`, `rebounds`, `assists`, `turnovers`.

#### NCAAB Team Stats JSONB (`stats` field)

Source: CBB Stats API. Keys use camelCase from the upstream API.

```json
{
  "points": 78,
  "rebounds": 34,
  "assists": 16,
  "turnovers": 11,
  "totalRebounds": 34,
  "offensiveRebounds": 8,
  "defensiveRebounds": 26,
  "fieldGoalsMade": 28,
  "fieldGoalsAttempted": 62,
  "threePointFieldGoalsMade": 7,
  "threePointFieldGoalsAttempted": 22,
  "freeThrowsMade": 15,
  "freeThrowsAttempted": 20,
  "steals": 6,
  "blocks": 3,
  "personalFouls": 18
}
```

> **Note:** Exact keys depend on CBB API response per game. All non-null stat fields from the API are stored. Metadata keys (`teamId`, `gameId`, `isHome`, `season`, etc.) are filtered out.

---

### PlayerStat (NBA / NCAAB)

Player-level boxscore stats. Returned in `playerStats` for NBA and NCAAB games. Top-level fields are convenience extractions; `rawStats` contains the full data.

```typescript
interface PlayerStat {
  team: string;
  playerName: string;
  minutes: number | null;
  points: number | null;
  rebounds: number | null;
  assists: number | null;
  rawStats: Record<string, any>;  // Full stat dict — league-specific keys (see below)
  source: string | null;
  updatedAt: string | null;
  normalizedStats: NormalizedStat[] | null;  // Same as TeamStat.normalizedStats
}
```

#### NBA Player `rawStats` JSONB

Source: NBA CDN API. All values are integers.

```json
{
  "position": "F",
  "minutes": 36.2,
  "points": 28,
  "rebounds": 8,
  "assists": 5,
  "fg_made": 10,
  "fg_attempted": 19,
  "three_made": 3,
  "three_attempted": 8,
  "ft_made": 5,
  "ft_attempted": 6,
  "offensive_rebounds": 2,
  "defensive_rebounds": 6,
  "steals": 2,
  "blocks": 1,
  "turnovers": 3,
  "personal_fouls": 2,
  "plus_minus": 12
}
```

> **Note:** `offensive_rebounds`, `defensive_rebounds`, and `personal_fouls` are present on all current player records.

#### NCAAB Player `rawStats` JSONB

Source: CBB Stats API. Keys are a mix of the raw API response and flattened convenience keys.

```json
{
  "position": "G",
  "minutes": 32.0,
  "points": 22,
  "rebounds": 5,
  "assists": 4,
  "fgMade": 8,
  "fgAttempted": 15,
  "fg3Made": 3,
  "fg3Attempted": 7,
  "ftMade": 3,
  "ftAttempted": 4,
  "steals": 2,
  "blocks": 0,
  "turnovers": 2,
  "fouls": 3
}
```

> **Note:** The raw CBB API keys (e.g. `fieldGoalsMade`, `threePointFieldGoals`) are also present alongside the flattened keys. The CBB API may return stats as nested objects (`{"total": 5, "offensive": 2}`) — these are preserved in `rawStats` as-is, with flattened integer versions added for convenience.

---

### OddsEntry

Betting odds for a game. Returned in the `odds` array of `GET /games/{gameId}`.

```typescript
interface OddsEntry {
  book: string;               // e.g. "fanduel", "draftkings"
  marketType: string;         // "h2h", "spreads", "totals", or prop market key
  marketCategory: string;     // "mainline", "player_prop", "team_prop", "alternate", etc.
  playerName: string | null;  // Player name for player prop markets
  description: string | null; // Market description (e.g. prop details)
  side: string | null;        // "home", "away", "over", "under"
  line: number | null;        // Spread or total value
  price: number | null;       // American odds (e.g. -110, +150)
  isClosingLine: boolean;     // True if this is the final pre-game line
  observedAt: string | null;  // ISO 8601
}
```

---

### NHL Player Stats

```typescript
interface NHLSkaterStat {
  team: string;
  playerName: string;
  toi: string | null;         // "MM:SS"
  goals: number | null;
  assists: number | null;
  points: number | null;
  shotsOnGoal: number | null;
  plusMinus: number | null;
  penaltyMinutes: number | null;
  hits: number | null;
  blockedShots: number | null;
  rawStats: object;
}

interface NHLGoalieStat {
  team: string;
  playerName: string;
  toi: string | null;
  shotsAgainst: number | null;
  saves: number | null;
  goalsAgainst: number | null;
  savePercentage: number | null;
  rawStats: object;
}
```

### PlayEntry

Plays returned in the `plays` array of `GET /games/{gameId}`.

```typescript
interface PlayEntry {
  playIndex: number;
  quarter: number | null;
  gameClock: string | null;
  periodLabel: string | null;   // Server-computed: "Q1", "1st Half", "P2", etc.
  timeLabel: string | null;     // Server-computed: "Q1 8:45", "2H 12:30", etc.
  playType: string | null;
  teamAbbreviation: string | null;
  playerName: string | null;
  description: string | null;
  homeScore: number | null;
  awayScore: number | null;
  tier: number | null;          // Server-computed: 1 (key), 2 (notable), 3 (routine)
  // Timeline enrichment fields
  scoreChanged: boolean | null;       // Whether score changed from previous play
  scoringTeamAbbr: string | null;     // Which team scored (e.g. "BOS")
  pointsScored: number | null;       // Points scored on this play
  homeScoreBefore: number | null;    // Home score before this play
  awayScoreBefore: number | null;    // Away score before this play
  phase: string | null;              // Game phase: "early", "mid", "late", "ot"
}
```

**Phase mapping by league:**

| League | Early | Mid | Late | OT |
|--------|-------|-----|------|----|
| NBA | Q1-Q2 | Q3 | Q4 | Q5+ |
| NCAAB | H1 | — | H2 | H3+ |
| NHL | P1 | P2 | P3 | P4+ |

### TieredPlayGroup

Consecutive Tier-3 plays collapsed into a summary. Returned in the `groupedPlays` array of `GET /games/{gameId}`.

```typescript
interface TieredPlayGroup {
  startIndex: number;
  endIndex: number;
  playIndices: number[];
  summaryLabel: string;    // e.g. "12 routine plays"
}
```

### GameDetailResponse

Full response for `GET /games/{gameId}`.

```typescript
interface GameDetailResponse {
  game: GameMeta;
  teamStats: TeamStat[];                // 2 entries (home + away)
  playerStats: PlayerStat[];            // NBA/NCAAB player stats
  nhlSkaters: NHLSkaterStat[] | null;   // NHL only
  nhlGoalies: NHLGoalieStat[] | null;   // NHL only
  mlbBatters: MLBBatterStat[] | null;   // MLB only — batter stats
  mlbPitchers: MLBPitcherStat[] | null; // MLB only — pitcher stats
  mlbAdvancedStats: MLBAdvancedTeamStats[] | null;         // MLB only — Statcast-derived team-level advanced stats
  mlbAdvancedPlayerStats: MLBAdvancedPlayerStats[] | null;  // MLB only — Statcast-derived player-level advanced stats
  odds: OddsEntry[];
  socialPosts: SocialPostEntry[];
  plays: PlayEntry[];
  groupedPlays: TieredPlayGroup[];
  derivedMetrics: Record<string, any>;
  rawPayloads: Record<string, any>;
  dataHealth: NHLDataHealth | null;     // NHL only
  oddsTable: OddsTableGroup[] | null;   // Structured odds table (see below)
  statAnnotations: StatAnnotation[] | null;  // Notable stat advantage callouts
}

interface OddsTableGroup {
  marketType: string;           // "spreads", "totals", "h2h"
  marketDisplay: string;        // "Spread", "Total", "Moneyline"
  openingLines: OddsTableLine[];
  closingLines: OddsTableLine[];
}

interface OddsTableLine {
  book: string;
  side: string;
  line: number | null;
  price: number;
  priceDisplay: string;         // e.g. "-110", "+150"
  isClosingLine: boolean;
  isBest: boolean;              // Best line for this side within closing lines
}

interface StatAnnotation {
  key: string;                  // e.g. "offensive_rebounds", "turnovers"
  text: string;                 // e.g. "BOS dominated the glass (+7 OREB)"
}

interface GameMeta {
  id: number;
  leagueCode: string;
  season: number;
  seasonType: string;             // "regular", "postseason"
  gameDate: string;               // ISO 8601 UTC
  homeTeam: string;
  awayTeam: string;
  homeScore: number | null;
  awayScore: number | null;
  status: string;                 // "scheduled", "pregame", "live", "final", "archived"
  scrapeVersion: number | null;
  hasBoxscore: boolean;
  hasPlayerStats: boolean;
  hasOdds: boolean;
  hasSocial: boolean;
  hasPbp: boolean;
  hasFlow: boolean;
  hasAdvancedStats: boolean;       // MLB Statcast-derived advanced stats available
  playCount: number;
  socialPostCount: number;
  lastScrapedAt: string | null;
  lastIngestedAt: string | null;
  lastPbpAt: string | null;
  lastSocialAt: string | null;
  lastOddsAt: string | null;
  lastAdvancedStatsAt: string | null;  // MLB Statcast advanced stats timestamp
  homeTeamXHandle: string | null;
  awayTeamXHandle: string | null;
  homeTeamAbbr: string | null;
  awayTeamAbbr: string | null;
  homeTeamColorLight: string | null;
  homeTeamColorDark: string | null;
  awayTeamColorLight: string | null;
  awayTeamColorDark: string | null;
  // Status convenience flags (same as GameSummary)
  isLive: boolean | null;
  isFinal: boolean | null;
  isPregame: boolean | null;
  isTrulyCompleted: boolean | null;
  readEligible: boolean | null;
  currentPeriodLabel: string | null;
  liveSnapshot: LiveSnapshot | null;
}
```

---

### NHLDataHealth

Data health check for NHL games. Returned in `dataHealth` field of `GameDetailResponse` (NHL only, null for other leagues).

```typescript
interface NHLDataHealth {
  skaterCount: number;
  goalieCount: number;
  isHealthy: boolean;
  issues: string[];     // e.g. ["missing_goalie_stats", "low_skater_count"]
}
```

---

### MLB Player Stats

MLB games return `mlbBatters` and `mlbPitchers` instead of generic `playerStats`.

```typescript
interface MLBBatterStat {
  team: string;
  playerName: string;
  position: string | null;
  atBats: number | null;
  hits: number | null;
  runs: number | null;
  rbi: number | null;
  homeRuns: number | null;
  baseOnBalls: number | null;
  strikeOuts: number | null;
  stolenBases: number | null;
  avg: string | null;
  obp: string | null;
  slg: string | null;
  ops: string | null;
  rawStats: Record<string, any>;
}

interface MLBPitcherStat {
  team: string;
  playerName: string;
  inningsPitched: string | null;
  hits: number | null;
  runs: number | null;
  earnedRuns: number | null;
  baseOnBalls: number | null;
  strikeOuts: number | null;
  homeRuns: number | null;
  era: string | null;
  pitchCount: number | null;
  strikes: number | null;
  rawStats: Record<string, any>;
}
```

---

### MLBAdvancedTeamStats

Statcast-derived advanced batting stats for one team in an MLB game. Returned in `mlbAdvancedStats` (MLB games only, null for other leagues).

```typescript
interface MLBAdvancedTeamStats {
  team: string;                    // Team name
  isHome: boolean;
  totalPitches: number;            // Total pitches seen
  ballsInPlay: number;            // Batted balls with launch speed data
  // Plate discipline
  zSwingPct: number | null;       // Zone swing rate (zone_swings / zone_pitches)
  oSwingPct: number | null;       // Outside swing rate (outside_swings / outside_pitches)
  zContactPct: number | null;     // Zone contact rate (zone_contact / zone_swings)
  oContactPct: number | null;     // Outside contact rate (outside_contact / outside_swings)
  // Quality of contact
  avgExitVelo: number | null;     // Average exit velocity (mph)
  hardHitPct: number | null;      // Hard-hit rate (launch speed >= 95 mph)
  barrelPct: number | null;       // Barrel rate (MLB barrel formula)
}
```

---

### MLBAdvancedPlayerStats

Statcast-derived advanced batting stats for individual batters in an MLB game. Same stat columns as `MLBAdvancedTeamStats`, plus player identification. Returned in `mlbAdvancedPlayerStats` (MLB games only, null for other leagues).

```typescript
interface MLBAdvancedPlayerStats {
  team: string;                    // Team name
  playerName: string;              // Batter name
  isHome: boolean;
  totalPitches: number;            // Total pitches seen
  ballsInPlay: number;             // Batted balls with launch speed data
  // Plate discipline
  zSwingPct: number | null;       // Zone swing rate
  oSwingPct: number | null;       // Outside swing rate
  zContactPct: number | null;     // Zone contact rate
  oContactPct: number | null;     // Outside contact rate
  // Quality of contact
  avgExitVelo: number | null;     // Average exit velocity (mph)
  hardHitPct: number | null;      // Hard-hit rate (launch speed >= 95 mph)
  barrelPct: number | null;       // Barrel rate (MLB barrel formula)
}
```

---

### TeamSummary

```typescript
interface TeamSummary {
  id: number;
  name: string;
  shortName: string;
  abbreviation: string;
  leagueCode: string;
  gamesCount: number;
  colorLightHex: string | null;   // Hex color for light backgrounds
  colorDarkHex: string | null;    // Hex color for dark backgrounds
}
```

### FairbetOddsResponse

```typescript
interface FairbetOddsResponse {
  bets: BetDefinition[];
  total: number;
  books_available: string[];
  market_categories_available: string[];
  games_available: GameDropdown[];
  ev_diagnostics: Record<string, number>;  // Aggregate stats: total_pairs, total_unpaired, etc.
}

interface BetDefinition {
  game_id: number;
  league_code: string;
  home_team: string;
  away_team: string;
  game_date: string;              // ISO 8601 UTC
  market_key: string;
  selection_key: string;
  line_value: number;
  market_category: string | null;
  player_name: string | null;
  description: string | null;
  true_prob: number | null;       // Fair probability from Pinnacle devig
  reference_price: number | null; // Pinnacle price for this side
  opposite_reference_price: number | null;
  books: BookOdds[];
  ev_confidence_tier: string | null;  // "high", "medium", "low"
  ev_disabled_reason: string | null;  // e.g. "no_strategy", reason EV is unavailable
  ev_method: string | null;           // e.g. "pinnacle_devig"
  has_fair: boolean;
  explanation_steps: ExplanationStep[] | null;  // Step-by-step math walkthrough
}

interface ExplanationStep {
  step_number: number;
  title: string;
  description: string;
  detail_rows: ExplanationDetailRow[];
}

interface ExplanationDetailRow {
  label: string;
  value: string;
  is_highlight: boolean;          // Client can bold/accent highlighted rows
}

interface BookOdds {
  book: string;
  price: number;
  observed_at: string;            // ISO 8601
  ev_percent: number | null;      // Expected value % (positive = +EV)
  implied_prob: number | null;    // Implied probability from this book's price
  is_sharp: boolean;              // true for Pinnacle reference line
  ev_method: string | null;
  ev_confidence_tier: string | null;
}

interface GameDropdown {
  game_id: number;
  matchup: string;                // "Away Team @ Home Team"
  game_date: string | null;       // ISO 8601
}
```

### GamePreviewScoreResponse

```typescript
interface GamePreviewScoreResponse {
  gameId: string;
  excitementScore: number;    // 0-100
  qualityScore: number;       // 0-100
  tags: string[];
  nugget: string;
}
```

### TimelineArtifactResponse

Returned by `GET /games/{gameId}/timeline` and `POST /games/{gameId}/timeline/generate`.

```typescript
interface TimelineArtifactResponse {
  gameId: number;
  sport: string;              // "NBA", "NHL", "NCAAB"
  timelineVersion: string;    // "v1"
  generatedAt: string;        // ISO 8601 UTC
  timeline: TimelineEvent[];  // Merged PBP + social + odds events
  summary: Record<string, any>;
  gameAnalysis: Record<string, any>;
}

// Timeline events have event_type-specific fields
interface TimelineEvent {
  event_type: "pbp" | "tweet" | "odds";
  phase: string;                    // "pregame", "q1", "q2", etc.
  intra_phase_order: number;        // Sort key within phase
  synthetic_timestamp: string;      // ISO 8601

  // PBP-specific fields
  play_index?: number;
  quarter?: number;
  game_clock?: string;
  description?: string;
  play_type?: string;
  team_abbreviation?: string;
  home_score?: number;
  away_score?: number;

  // Social-specific fields
  author?: string;
  text?: string;
  role?: string;                    // "hype", "reaction", "momentum", etc.

  // Odds-specific fields
  odds_type?: string;               // "opening_line", "closing_line", "line_movement"
  book?: string;                    // "fanduel", "draftkings", etc.
  markets?: Record<string, any>;
  movements?: Array<Record<string, any>>;  // Only on line_movement events
}
```

---

## Appendix: Play Types by Sport

### NBA Play Types
- `tip` - Jump ball / tip-off
- `made_shot` - Made field goal
- `missed_shot` - Missed field goal
- `3pt` - Three-point shot
- `free_throw` - Free throw attempt
- `rebound` - Offensive or defensive rebound
- `turnover` - Turnover
- `steal` - Steal
- `block` - Blocked shot
- `foul` - Personal foul
- `timeout` - Timeout
- `substitution` - Player substitution
- `period_end` - End of period

### NHL Event Types
- `faceoff` - Face-off
- `shot` - Shot on goal
- `goal` - Goal scored
- `save` - Goalie save
- `miss` - Missed shot
- `block` - Blocked shot
- `hit` - Body check
- `penalty` - Penalty called
- `giveaway` - Puck giveaway
- `takeaway` - Puck takeaway
- `period_start` - Period start
- `period_end` - Period end
- `stoppage` - Play stoppage

### NCAAB Play Types
- Similar to NBA play types
- `made_shot`, `missed_shot`, `3pt`, `free_throw`
- `rebound`, `turnover`, `steal`, `block`, `foul`
- `timeout`, `substitution`
