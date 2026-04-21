# Plan: Admin dashboard endpoints (`/api/admin/stats`, `/api/admin/poll-health`)

## Context

The frontend `admin.dock108.dev` is live. It mounts a `SuperAdminDashboard` (`src/pages/superadmin/SuperAdminDashboard.tsx` in `masters-pool-web`) that polls two endpoints on this backend:

- `GET /api/admin/stats` — one-shot summary card grid (4 tiles).
- `GET /api/admin/poll-health` — polled every 60s to warn when tournament data hasn't refreshed during an active tournament window.

Both return **404 today**. The frontend renders a "Failed to load stats" banner and empty cards. We want the dashboard populated from real data.

**Auth model:**
- `admin.dock108.dev` is already gated by HTTP Basic Auth at the Caddy layer (`admin` / `4815162342`), so only the operator ever reaches this SPA.
- The SPA calls these endpoints through the same-origin `/api/` reverse proxy on the masters-pool-web nginx container, which proxies to `sda.dock108.dev` and injects the `X-API-Key` header (admin-tier `API_KEY`, not `CONSUMER_API_KEY`).
- **These endpoints should require `verify_api_key` only — not `require_admin`.** The JWT/role flow is for consumer apps; the admin-tier API key already scopes this to operator use, and Caddy Basic Auth provides a second layer.

## Response contracts (snake_case — match frontend `src/types/domain.ts`)

### `GET /api/admin/stats` → 200

```json
{
  "total_pools": 3,
  "total_entries": 142,
  "active_clubs": 2,
  "mrr_cents": 9800
}
```

Rules:
- `total_pools`: count of rows in `golf_pools` **excluding** `status IN ('archived', 'draft')`. Live + locked + final pools count; drafts and archives don't.
- `total_entries`: count of rows in `golf_pool_entries` across all pools, any status. No filtering.
- `active_clubs`: count of distinct `club_code` values in `golf_pools` where `status IN ('open', 'locked', 'live')`. A club with only a `final` pool is not "active."
- `mrr_cents`: sum of the monthly-equivalent amount for all Stripe subscriptions in status `active` or `trialing`, in cents. If you don't have subscriptions wired up yet, return `0` — the frontend renders `$0` cleanly. **Do not omit the field.**

All four fields are required and always integers (zero, not null, when empty).

### `GET /api/admin/poll-health` → 200

```json
{
  "tournaments": [
    {
      "pool_id": 1,
      "pool_name": "RVCC Masters Pool 2026",
      "tournament_name": "The Masters 2026",
      "last_polled_at": "2026-04-21T14:05:12Z",
      "is_in_window": true,
      "is_stale": false
    }
  ],
  "checked_at": "2026-04-21T14:30:00Z"
}
```

Rules:
- One row per pool where `status IN ('open', 'locked', 'live')` AND `scoring_enabled = true`. Drafts and finalized pools are excluded.
- `last_polled_at`: most recent timestamp of a successful scoring/data poll for the pool's tournament. `null` if never polled. Source this from whatever table your existing scraper writes to — e.g. a `tournament_poll_log`, a `last_synced_at` column on the tournament, or `max(created_at)` on recent `leaderboard_snapshots`. Whatever's authoritative for "did fresh data land."
- `is_in_window`: `true` when "now" is between the tournament's start and end (inclusive). For the Masters, roughly Thursday 07:00 through Sunday 20:00 local time of tournament week. If you model it as `tournament.start_date` and `tournament.end_date`, compare against those. Off-window tournaments still appear in the list but never show as stale.
- `is_stale`: `true` **only if** `is_in_window = true` AND `(now - last_polled_at) > 30 minutes`. Never `true` outside the window. Null `last_polled_at` during window → `is_stale = true`.
- `checked_at`: the server's current UTC timestamp when the response was generated.

Tournaments array may be empty (`[]`); frontend renders "No active tournaments."

## Implementation

### Router

**New:** `api/app/routers/admin/platform.py` (put it next to existing admin routers, or add to the nearest admin module — match your existing convention).

```python
router = APIRouter(prefix="/api/admin", tags=["admin", "platform"])

class AdminStatsResponse(BaseModel):
    total_pools: int
    total_entries: int
    active_clubs: int
    mrr_cents: int

class TournamentPollHealth(BaseModel):
    pool_id: int
    pool_name: str
    tournament_name: str
    last_polled_at: datetime | None
    is_in_window: bool
    is_stale: bool

class AdminPollHealthResponse(BaseModel):
    tournaments: list[TournamentPollHealth]
    checked_at: datetime

@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(db: AsyncSession = Depends(get_db)) -> AdminStatsResponse:
    ...

@router.get("/poll-health", response_model=AdminPollHealthResponse)
async def get_poll_health(db: AsyncSession = Depends(get_db)) -> AdminPollHealthResponse:
    ...
```

**Important:** use default Pydantic snake_case serialization. Do NOT use `alias_generator=to_camel` on these responses — the frontend types are snake_case. The `POST /api/onboarding/club-claims` endpoint happens to emit `claimId`/`receivedAt` (camelCase), which is already a minor mismatch with the frontend's `ClubClaim` type; don't repeat that here.

### Register with API-key-only auth

In `api/main.py`, register the router with `auth_dependency` (which is `[Depends(verify_api_key)]`), not `admin_dependency`:

```python
app.include_router(platform.router, dependencies=auth_dependency)
```

Mount it near the other admin routers (around line 244 where `timeline_jobs.router` is registered), but **without** `require_admin`. Rationale: the endpoint is consumer-facing from the admin SPA; admin-tier `API_KEY` is the right gate. Role-based `require_admin` is for JWT-authenticated users, which this flow doesn't have.

### Data sources

Pick one canonical source for `last_polled_at` — the scraper's own log is ideal. Options, in rough order of preference:

1. **Scraper log table** (if one exists): `SELECT max(completed_at) FROM scraper_runs WHERE tournament_id = ? AND status = 'success'`.
2. **Tournament table column**: add/use a `last_polled_at` column on `tournaments`, updated by the scraper on success.
3. **Leaderboard snapshots**: `SELECT max(created_at) FROM leaderboard_snapshots WHERE pool_id = ?` — workable but indirect.

Pick whichever lines up with how the existing Celery/polling code is already writing. If none of the above exists, add it to the scraper's success path rather than inventing a new mechanism for this endpoint.

For tournament windows: if `tournaments` already has `start_date`/`end_date` columns, use those. Otherwise hardcode the Masters 2026 window for now (Thursday 2026-04-09 07:00 ET through Sunday 2026-04-12 20:00 ET) and file a follow-up for a proper schema. Hardcoding is fine — this table has 4 majors a year max.

### Tests

**New:** `api/tests/test_admin_platform.py`

Cover:

- `GET /api/admin/stats`:
  - Empty DB → all four fields return `0`.
  - Seeded 2 pools (1 live, 1 archived), 5 entries, 1 active club → `total_pools=1`, `total_entries=5`, `active_clubs=1`.
  - No Stripe subscriptions → `mrr_cents=0`.
  - Response schema strictly matches (no extra fields, no camelCase aliases).
  - **Without `X-API-Key` header → 401.** Dedicated regression test, because this endpoint must not require admin JWT but must require the admin-tier API key.

- `GET /api/admin/poll-health`:
  - No live pools → `tournaments: []`.
  - Live pool polled 5 minutes ago, in-window → `is_stale=false`.
  - Live pool polled 45 minutes ago, in-window → `is_stale=true`.
  - Live pool never polled, in-window → `is_stale=true`, `last_polled_at=null`.
  - Live pool polled 45 minutes ago, off-window → `is_stale=false` (window rule wins).
  - `checked_at` is within a second of "now" (allow drift in the assertion).

Freeze time with `freezegun` or equivalent for the staleness tests — you'll have enough of those to justify a small helper.

Coverage budget: these two endpoints should hit ≥95% branch coverage so the 80% repo-wide floor stays green.

## Critical files

**New**
- `api/app/routers/admin/platform.py` (or slot into whichever existing admin module matches your directory conventions)
- `api/tests/test_admin_platform.py`

**Modify**
- `api/main.py` — register `platform.router` with `auth_dependency`, near the existing admin routers around line 244
- Possibly `api/app/db/<scraper log model>.py` if you add or use a new table/column for `last_polled_at`

## Verification

1. `alembic upgrade head` if any schema change; `pytest tests/test_admin_platform.py -v --cov=app.routers.admin.platform` → ≥95% coverage on the new module.
2. **Local curl** against the running API with the admin key:
   ```bash
   curl -sI http://localhost:8000/api/admin/stats                                # 401
   curl -s  http://localhost:8000/api/admin/stats  -H "X-API-Key: $API_KEY" | jq # 200 + shape
   curl -s  http://localhost:8000/api/admin/poll-health -H "X-API-Key: $API_KEY" | jq
   ```
3. **End-to-end against deployed admin SPA** after deploy:
   ```bash
   curl -u admin:4815162342 https://admin.dock108.dev/api/admin/stats       # via nginx proxy
   ```
   Then load `admin.dock108.dev` in a browser: stat cards should show real numbers, poll-health section should list any live pools with correct status badges (OK / STALE / OFF-WINDOW).

## Deployment

Migration (if any) runs automatically on deploy via `docker compose --profile prod run --rm migrate`. No env-var additions needed — existing `API_KEY` is already set. Frontend doesn't need to change once these endpoints return 200; the SPA is already wired.
