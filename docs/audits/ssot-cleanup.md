# SSOT Cleanup — Destructive Pass

**Date:** 2026-04-22
**Branch:** main

---

## Diff-Driven Deletion Summary

### 1. Dead Feature Flags — `api/app/config.py` (prior pass)

Three FairBet flags were removed because they were either always-on or always-off with no mechanism to change them in any deployed environment (production, staging, or CI).

| Flag | Default | Effect |
|------|---------|--------|
| `FAIRBET_CURSOR_ENABLED` | `True` | Guard `if cursor and not settings.fairbet_cursor_enabled: raise HTTPException(...)` was unreachable |
| `FAIRBET_LIGHT_DEFAULT_ENABLED` | `True` | Ternary `sort_by or ("game_time" if ... else "ev")` — `"ev"` branch was unreachable |
| `FAIRBET_REDIS_LIMITER_ENABLED` | `False` | Entire Redis-backed rate-limit branch for `/api/fairbet/odds` was dead |

**Files changed:**
- `api/app/config.py`: removed three flag fields and their validator checks
- `api/app/routers/fairbet/odds.py`: hardcoded `sort_resolved = sort_by or "game_time"`, removed `fairbet_cursor_enabled` guard
- `api/app/middleware/rate_limit.py`: removed `fairbet_redis_limiter_enabled` conditional block, removed `asyncio` import (no longer needed), removed `redis_allow_request` import, removed `_FAIRBET_PREFIX` constant

### 2. Orphaned Config Field — `resend_api_key` (prior pass)

`RESEND_API_KEY` was declared in `Settings` but never read anywhere in the API codebase. The email service (`services/email.py`) has only `smtp` and `ses` backends — Resend was never implemented.

**Files changed:**
- `api/app/config.py`: removed `resend_api_key` field

### 3. Dead Limiter Settings — `fairbet_odds_limiter_*` (prior pass)

`fairbet_odds_limiter_requests` and `fairbet_odds_limiter_window_seconds` were only consumed inside the now-deleted Redis limiter branch. No other code referenced them.

**Files changed:**
- `api/app/config.py`: removed both fields and their positive-integer validator checks

### 4. Backward-Compat Shim — `_build_base_filters` in `odds.py` (prior pass)

The shim existed to strip the `book` kwarg before delegating to `build_base_filters`, which does not accept `book`. It was documented as "backward-compatible symbol used by tests/importers." Both internal call sites already passed `book=book` through the shim.

**Files changed:**
- `api/app/routers/fairbet/odds.py`: deleted `_build_base_filters`, both call sites now call `build_base_filters` directly (without `book=book`), removed now-unused `settings` import
- `api/tests/test_fairbet_odds.py`: removed `_build_base_filters` import and `TestBuildBaseFilters` class (3 tests, all testing the removed shim)

### 5. Dead Test Scaffolding — `fairbet_redis_limiter_enabled` in Tests (prior pass)

Six test helper calls in `test_api_key_scopes.py` set `s.fairbet_redis_limiter_enabled = False` on a mock to prevent the Redis limiter from running. After deleting the branch the attribute has no effect.

**Files changed:**
- `api/tests/test_api_key_scopes.py`: removed all six `s.fairbet_redis_limiter_enabled = False` lines

### 6. Dead Flag — `HISTORY_ENABLED` in scraper live-odds Redis store (this pass)

`scraper/sports_scraper/live_odds/redis_store.py` declared `HISTORY_ENABLED = True` at module scope and branched on it inside `write_live_snapshot()`. There was no mechanism to flip the flag (not env-driven, not in `settings`, no test patches), so `if HISTORY_ENABLED:` was unconditionally true and the `else` branch was unreachable. The history ring buffer is consumed by `read_live_history()` and its tests, so the behavior stays — only the dead guard was removed.

**Files changed:**
- `scraper/sports_scraper/live_odds/redis_store.py`: removed the `HISTORY_ENABLED = True` constant and unwrapped the `if HISTORY_ENABLED:` block in `write_live_snapshot()` so the history write runs unconditionally.

---

## SSOT Verification

| Domain | Authoritative Module |
|--------|---------------------|
| FairBet odds endpoint | `api/app/routers/fairbet/odds.py` |
| Base query filter construction | `api/app/routers/fairbet/odds_core.py::build_base_filters` |
| Rate limiting | `api/app/middleware/rate_limit.py` (in-memory, three tiers: auth-strict, onboarding, admin, global) |
| Redis rate limiting (entry submissions) | `api/app/services/entry_rate_limit.py` via `fairbet_runtime.redis_allow_request` |
| Email transports | `api/app/services/email.py` (`smtp` and `ses` only; Resend removed) |
| Settings | `api/app/config.py::Settings` |
| League/sport config (scraper) | `scraper/sports_scraper/config_sports.py` |
| League/sport config (API — superset: adds season audit baselines) | `api/app/config_sports.py` |
| Live in-game odds cache (scraper writer) | `scraper/sports_scraper/live_odds/redis_store.py` |
| Live in-game odds cache (API reader, circuit-breaker variant) | `api/app/services/live_odds_redis.py` |
| MLB pitcher/player rolling profiles | `api/app/analytics/services/mlb_player_profiles.py` |
| MLB roster lookups | `api/app/analytics/services/mlb_roster_service.py` |

---

## Risk Log

### Retained: `auth_enabled` / `AUTH_ENABLED=false` dev bypass (prior pass)

`api/app/dependencies/roles.py` still has `if not settings.auth_enabled: return "admin"`. This was considered for removal but kept because:

- It is a valid dev-only escape hatch, not a disabled production feature
- The production validator raises if `AUTH_ENABLED=false` is set in production/staging
- Removing it would require devs to provision real JWTs for local testing

### Retained: `redis_allow_request` in `fairbet_runtime.py` (prior pass)

The function is still used by `api/app/services/entry_rate_limit.py` for pool entry abuse prevention. Only the unused import in `rate_limit.py` was removed.

### Retained: MLB re-export shim in `profile_service.py`

`profile_service.py` re-exports `_pitcher_profile_from_boxscore`, `_pitcher_profile_from_statcast`, `get_pitcher_rolling_profile`, `get_player_rolling_profile` from `mlb_player_profiles`, and `_fetch_mlb_api_roster`, `get_team_roster` from `mlb_roster_service`. It is labeled "for backward compatibility," but `mlb_player_profiles.py` deliberately looks these helpers up via `import app.analytics.services.profile_service as _ps` (see the comment at `mlb_player_profiles.py:124–127`) so that test suites using `mock.patch("app.analytics.services.profile_service._pitcher_profile_from_*")` still intercept the real call. Removing the re-exports would require rewriting ~10 patch targets across `test_profile_service_extended.py` and `test_coverage_boost.py` with no production benefit. Left in place; the "backward compatibility" comment in `profile_service.py` has been kept because the re-exports are in fact load-bearing for the test mock pattern.

### Retained: `get_team_info(sport: str = "mlb")` default

The default is actually used — `api/app/routers/simulator_mlb.py` and `api/app/analytics/api/_simulation_helpers.py` both call `get_team_info(abbr, db=db)` without passing `sport`. Since the two callers are either MLB-specific (`simulator_mlb`) or dispatched from MLB paths (`_simulation_helpers`), the default is not dead. Removing it would require a caller-by-caller audit and plumbing `sport` through — out of scope for this SSOT pass. Documented as "live default," not "backward-compat."

### Retained: `pa_rates` / `avg_total_runs` / `median_total_runs` / `one_run_game_pct` aliases in `event_aggregation.py` and `simulation_runner.py`

These are labeled "backward-compat" in code comments, but the Next.js admin UI (`web/src/app/admin/analytics/batch/page.tsx`, `web/src/components/admin/GameDetailModal.tsx`) and the batch-sim enrichment step (`api/app/tasks/_batch_sim_enrichment.py`) both read these fields at runtime. The comments are misleading — the fields are part of the active API contract. No deletion; the misleading comments were left alone to avoid churn.

### Retained: `NotImplementedError` stubs in `scrapers/base.py`

`pbp_url`, `fetch_games_for_date`, `fetch_play_by_play`, `fetch_single_boxscore` on `BaseSportsReferenceScraper` raise `NotImplementedError`. These are intentional abstract-method contracts for subclasses to override; not dead code.

---

## Sanity Check

```
# Confirm no remaining references to removed symbols
grep -rE "fairbet_cursor_enabled|fairbet_light_default_enabled|fairbet_redis_limiter_enabled|fairbet_odds_limiter_requests|fairbet_odds_limiter_window|resend_api_key|_build_base_filters|HISTORY_ENABLED" api/ scraper/
```

Expected: zero results (excluding this audit file).

Verified on 2026-04-22:
- `HISTORY_ENABLED` — 0 hits across `api/` and `scraper/`.
- Prior-pass symbols — 0 hits (unchanged since prior audit).
- `python -m py_compile scraper/sports_scraper/live_odds/redis_store.py` — passes.
