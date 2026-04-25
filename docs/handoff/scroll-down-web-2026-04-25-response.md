# SDA → scroll-down-web — response to 2026-04-25 handoff findings

Status: shipped on branch `scrolldown_changes` (commits `090760fe` + SSOT cleanup). All changes are additive on the wire, with two exceptions called out below. Pull the latest API image and follow the per-issue actions to drop your local workarounds.

## TL;DR action items for your team

1. **Drop `deepSnakeKeys` proxy transform on `/api/games`, `/api/games/{id}`, `/api/games/{id}/flow`, `/api/fairbet/odds`, `/api/golf/*`.** Those endpoints have always been camelCase on the wire. Your handoff classified them as snake_case — that was looking at the OpenAPI schema field names (the Python identifiers), not the response. Verify with `curl ... | jq 'keys'` and confirm before removing.
2. **Use `bet.homeTeamAbbr` / `bet.awayTeamAbbr` directly** when calling the simulator. Drop the name→abbr lookup against `/api/simulator/{sport}/teams`.
3. **Send `X-API-Key` from CI.** You now get a separate per-key bucket with 5× the per-IP budget — enough to safely run 10+ concurrent workers off one key.
4. **Drop your `dedupeTeams()` shim for MLB/NBA/NHL.** The response no longer leaks cross-sport rows.
5. **Retry on `503` from `/api/analytics/batch-simulate-jobs` instead of `test.skip()`.** Honour the `Retry-After` header (we send 5s).
6. **You can lower your simulator client timeout** from 30s back to ~10s for normal iteration counts. Flag us if you still see >10s tail under your CI load — we have a Celery-dispatch fallback designed but not shipped.

---

## Per-issue response

### Issue 1 — camelCase vs snake_case inconsistency

**What you reported:** mixed conventions across endpoints; specifically called out `/api/fairbet/odds`, `/api/games`, `/api/games/{id}`, `/api/games/{id}/flow`, `/api/golf/*` as snake_case.

**What we found:** all five of those are camelCase on the wire and have been for the life of those routes. The Pydantic schemas use snake_case Python attribute names with explicit `Field(alias="camelCase")` or `alias_generator=to_camel`, and FastAPI's default `response_model_by_alias=True` is in effect. We confirmed by reading every schema and checked there's no `response_model_by_alias=False` override on those routes. Most likely your team was looking at the OpenAPI/JSON-schema field names (which use the snake_case identifier) rather than actual response keys.

Two endpoints **were** legitimately mixed and we fixed them:
- `MeResponse` (`/auth/me`) had no alias config — now does.
- `TeamsResponse` (`/api/simulator/{sport}/teams`) wrapper had no alias config while its inner `TeamInfo` did.

**Wire impact:** zero (the inconsistent endpoints had no underscore field names to flip).

**What you need to do:**
- Drop `deepSnakeKeys` from your proxy edge for `/api/games`, `/api/games/{id}`, `/api/games/{id}/flow`, `/api/fairbet/odds`, `/api/golf/*`. Verify with one `curl`:
  ```bash
  curl -H "X-API-Key: ..." "https://<api>/api/games?limit=1" | jq '.games[0] | keys'
  # Expect: ["awayTeam", "gameDate", "hasBoxscore", "homeTeam", "id", "leagueCode", ...]
  ```
- `/auth/*` and `/api/fairbet/live` were correctly classified by you as camelCase — keep those proxy transforms in place if they're still doing useful work elsewhere.

### Issue 2 — Simulator only accepts abbreviations; bet payloads expose only full names

**What we shipped:** added two nullable fields on every bet returned by `/api/fairbet/odds` and `/api/fairbet/live`:
- `homeTeamAbbr` (e.g. `"LAL"`)
- `awayTeamAbbr` (e.g. `"BOS"`)

These are populated from the same team relations the existing `homeTeam` / `awayTeam` strings come from. Both fields are nullable — if a bet references a game whose home/away team mapping is missing in the DB, the abbr will be `null`. (This is the same condition that already produces `"Unknown"` for the full-name field today.)

We did **not** add support for full team names in the simulator. The single contract is "use abbreviations" — adding the abbr on every bet payload solves your problem without introducing name-ambiguity (multiple "Cardinals", etc.).

**What you need to do:**
- In `apps/web/src/services/simulator.ts` (or wherever the Monte Carlo call is built), use `bet.homeTeamAbbr` / `bet.awayTeamAbbr` directly:
  ```ts
  const result = await api.simulator.run(sport, {
    home_team: bet.homeTeamAbbr,
    away_team: bet.awayTeamAbbr,
    iterations: 10000,
  });
  ```
- Delete the `GET /api/simulator/{sport}/teams` lookup + name→abbr mapping. You can keep that endpoint as a fallback for the rare `null` abbr case if you want defensive behavior, but the common path is now zero round-trips.

### Issue 3 — `/api/simulator/{sport}/teams` returns cross-sport teams

**What we shipped:**
- Generalized the canonical-abbreviation filter (which existed only for MLB) to MLB, NBA, and NHL. Each query now applies a `WHERE abbreviation IN (canonical set)` clause. NCAAB is intentionally excluded — D-I has 350+ schools and no canonical short list, so we rely on `league_id` alone there.
- Lifted the dispatch table to `app.analytics.sports.team_filters` so the same SSOT is shared by `/api/simulator/{sport}/teams` and `/api/analytics/{sport}/teams`.
- Added a `sport` field to every `TeamInfo` so consumers can detect (and discard) any future cross-sport leakage on a per-team basis.

**Wire impact:** additive — every `team` item now also carries `"sport": "mlb"` (or "nba"/"nhl"/"ncaab"). The outer wrapper still has its top-level `sport` field as before.

**What you need to do:**
- Delete the `dedupeTeams()` shim entirely for MLB, NBA, and NHL — the API response is now sport-scoped server-side.
- For NCAAB, keep your client-side defensive logic if you have any (we cannot canonical-filter that league). The `sport` field on each team still helps you sanity-check.
- The bug where your dedupe was reading `t.games_with_stats` against a `gamesWithStats` payload (per your handoff): the upstream was always camelCase, so this is a pure web-side fix you can pair with the dedupe deletion.

### Issue 4 — Per-IP rate limiting on `/api/games` and others

**What we shipped:**

#### Per-API-key buckets
The global rate-limit tier now keys on `X-API-Key` when present, falling back to per-IP only for unkeyed requests:

| Bucket | Limit | Configured by |
|---|---|---|
| **Keyed** (X-API-Key present) | **600 req/min** (default) | `RATE_LIMIT_REQUESTS_KEYED` |
| **IP** (no key) | **120 req/min** (default) | `RATE_LIMIT_REQUESTS` |

Keys are independent of IPs: 8 CI workers behind one IP, all sending the same `X-API-Key`, share the keyed bucket — so you get the full 600/min budget even if everyone is on `127.0.0.1`. Different keys (or no key) are completely independent buckets.

429 responses still include `Retry-After: <window>` (default 60s).

#### Response cache
TTL-based Redis caching now covers all read-heavy endpoints:

| Endpoint | TTL | Notes |
|---|---|---|
| `/api/fairbet/odds` | 15s (existing, unchanged) | |
| `/api/games` | **15s (new)** | Keyed by query params |
| `/api/fairbet/live` | **5s (new)** | Short TTL — live odds change fast |

Cached responses emit:
- `Cache-Control: public, max-age=<ttl>`
- `X-Cache: HIT` (served from cache) / `MISS` (just computed and cached) / `BYPASS` (request had `Authorization` or `Cookie`, so not cached)

Authenticated requests (any `Authorization` or `Cookie` header) bypass the cache so per-user state can never leak through a shared key.

**What you need to do:**

1. **Make sure CI sends `X-API-Key`.** If your Playwright config already sets it via the API client, you're done. Otherwise:
   ```ts
   // playwright.config.ts (or wherever you set extraHTTPHeaders)
   use: {
     extraHTTPHeaders: {
       'X-API-Key': process.env.SDA_CI_API_KEY,
     },
   },
   ```
2. **You can scale to ~10 concurrent CI requests safely** under the keyed bucket. If you're still hitting 429s with one key and ≤10 concurrent workers, ping us and we'll bump `RATE_LIMIT_REQUESTS_KEYED` server-side.
3. **Optionally, wire your CDN / browser cache to honor `Cache-Control`.** Most setups already do. Public `max-age` is set explicitly so revalidation isn't required.
4. **Watch `X-Cache` headers in dev** if you want to confirm the cache is actually collapsing duplicate worker requests. A burst of 8 identical Playwright loads should produce 1× MISS and 7× HIT.

### Issue 5 — Monte Carlo latency variance under load

**What we shipped:** every call site of `_service.run_full_simulation` is now wrapped in `await asyncio.to_thread(...)`. The simulator engine is CPU-bound (10k–50k iterations of pure-Python loops) — running it inline used to block the ASGI worker for the full duration, so concurrent requests serialized on a single worker thread.

Applied at all three call sites:
- `POST /api/simulator/{sport}` (generic multi-sport)
- `POST /api/simulator/mlb` (lineup-aware)
- `POST /api/analytics/simulate` (admin diagnostics)

We added a concurrency test that proves 4 simultaneous 0.25s sims complete in <0.6s (parallel) instead of ~1s (serial).

**What we did NOT ship:** Celery dispatch for >10k iteration calls. We have a design for it gated behind a `SIMULATOR_ASYNC_THRESHOLD` env var, but it adds polling complexity for the client. We'd rather see if `to_thread` alone is enough under your real CI load before shipping it. Tell us the p50/p95 you observe after this change.

**What you need to do:**
- **Lower your client timeout** from 30s back toward 10s for normal-iteration calls (≤10k). Tail latency should drop substantially.
- **If you see consistent >10s tails on >10k-iteration calls under concurrent CI**, ping us — we'll ship the Celery dispatch path.
- Queue-position headers (which you asked about): we deferred. If `to_thread` solves the variance, queue-position adds complexity for nothing. Revisit only if the latency picture stays bad.

### Issue 6 — Forwarded 5xx responses

**What we shipped:**
- `/api/analytics/batch-simulate-jobs` and `/api/analytics/batch-simulate-job/{id}` now wrap DB calls in try/except. Transient errors (DB connection failures, timeouts) return `503` with `Retry-After: 5`. Genuinely-bug failures (e.g. malformed `results` JSON discovered during serialization) still surface but as `500` with stable shape.
- Per-row serialization isolated: if one corrupted job row breaks `_serialize_batch_sim_job`, the rest of the list still returns `200` with that single row replaced by `{"id": <n>, "error": "serialization_failed"}` — instead of 500ing the whole list.

**What we did NOT ship:** exposing internal exception types or signatures. That's an attack-surface concern. Use `Retry-After` as the contract instead.

**What you need to do:**
- For `/api/analytics/batch-simulate-jobs`: replace `test.skip("upstream returned 500")` with a retry loop that honours `Retry-After`. After two retries that still 503, then skip. We expect the retry path to recover almost always — true 5xx persistence indicates a real outage.
- For `/api/fairbet/live` and `/api/games` 5xx under load: the new caching should reduce these substantially because identical requests collapse server-side. Per-key rate limit also helps. If you still see them, file a fresh report — the prior 5xx frequency was load-induced, not a permanent contract issue.

---

## Bonus changes (SSOT cleanup pass)

These weren't on your handoff but you'll see them in the diff:

1. **`GET /api/simulator/mlb/teams`** previously had a dedicated handler with a slightly different shape (no `sport` field). It now serves the SSOT generic handler. **Wire change: additive** — `sport: "mlb"` now appears in the response and on every team item. No fields were removed.
2. **`GET /api/analytics/mlb-teams`** is now a 1-line delegate to `/api/analytics/{sport}/teams?sport=mlb`. Wire shape unchanged.

Neither change should require action on your side. Mentioned for diff completeness.

---

## What we didn't change (for the record)

- **Did not flip the codebase to snake_case.** Your handoff suggested standardizing on snake_case across all endpoints. We declined — the codebase is consistently camelCase except for the two leaks we plugged (Issue 1 fixes). Flipping the convention would break every existing consumer including your auth proxy.
- **Did not expose 5xx exception types.** Per-error retryability is communicated via `Retry-After` instead.
- **Did not add queue-position headers to the simulator.** Wait-and-see based on `to_thread` results.
- **Did not change `POST /api/simulator/{sport}` to accept full team names.** Single-contract abbreviation-only with the new `*Abbr` fields on bet payloads is cleaner.

---

## Quick verification checklist

After deploying our changes, you should be able to confirm:

```bash
# 1. /api/games is camelCase
curl -s -H "X-API-Key: $KEY" "https://<api>/api/games?limit=1" | jq '.games[0].homeTeam'
# → "Boston Celtics" (not null)

# 2. Bet payload has abbrs
curl -s -H "X-API-Key: $KEY" "https://<api>/api/fairbet/odds?limit=1" | jq '.bets[0] | {homeTeam, homeTeamAbbr, awayTeam, awayTeamAbbr}'
# → all four fields populated (abbr may be null only for unmapped teams)

# 3. Teams response is sport-scoped
curl -s -H "X-API-Key: $KEY" "https://<api>/api/simulator/mlb/teams" | jq '.teams[].abbreviation' | sort -u | wc -l
# → 30 (the 30 canonical MLB abbreviations, no NFL/NHL leak)

# 4. Cache headers present
curl -s -I -H "X-API-Key: $KEY" "https://<api>/api/games?limit=1" | grep -iE "cache-control|x-cache"
# → Cache-Control: public, max-age=15
# → X-Cache: MISS  (or HIT on second hit within 15s)

# 5. Per-key bucket
# Hit /api/games 121 times in <60s with no X-API-Key → 1 of the last few should 429
# Hit /api/games 121 times in <60s WITH X-API-Key → all 200
```

---

## Open questions for your team

1. After dropping the `deepSnakeKeys` shims and the `dedupeTeams` fallback, what's the new flake/skip rate on `@live-upstream` tests? We're targeting ≤2 skips per CI run on a healthy day; please share the next two CI runs' numbers.
2. Do you want us to send a one-time agent in 2 weeks to review whether the simulator latency variance closed with `to_thread` alone, or whether we should ship the Celery dispatch path? Easier to decide with your post-rollout numbers in hand.

— SDA team, 2026-04-25
