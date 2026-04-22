# SSOT Cleanup — Destructive Pass

**Date:** 2026-04-22  
**Branch:** main

---

## Diff-Driven Deletion Summary

### 1. Dead Feature Flags — `api/app/config.py`

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

### 2. Orphaned Config Field — `resend_api_key`

`RESEND_API_KEY` was declared in `Settings` but never read anywhere in the API codebase. The email service (`services/email.py`) has only `smtp` and `ses` backends — Resend was never implemented.

**Files changed:**
- `api/app/config.py`: removed `resend_api_key` field

### 3. Dead Limiter Settings — `fairbet_odds_limiter_*`

`fairbet_odds_limiter_requests` and `fairbet_odds_limiter_window_seconds` were only consumed inside the now-deleted Redis limiter branch. No other code referenced them.

**Files changed:**
- `api/app/config.py`: removed both fields and their positive-integer validator checks

### 4. Backward-Compat Shim — `_build_base_filters` in `odds.py`

The shim existed to strip the `book` kwarg before delegating to `build_base_filters`, which does not accept `book`. It was documented as "backward-compatible symbol used by tests/importers." Both internal call sites already passed `book=book` through the shim.

**Files changed:**
- `api/app/routers/fairbet/odds.py`: deleted `_build_base_filters`, both call sites now call `build_base_filters` directly (without `book=book`), removed now-unused `settings` import
- `api/tests/test_fairbet_odds.py`: removed `_build_base_filters` import and `TestBuildBaseFilters` class (3 tests, all testing the removed shim)

### 5. Dead Test Scaffolding — `fairbet_redis_limiter_enabled` in Tests

Six test helper calls in `test_api_key_scopes.py` set `s.fairbet_redis_limiter_enabled = False` on a mock to prevent the Redis limiter from running. After deleting the branch the attribute has no effect.

**Files changed:**
- `api/tests/test_api_key_scopes.py`: removed all six `s.fairbet_redis_limiter_enabled = False` lines

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

---

## Risk Log

### Retained: `auth_enabled` / `AUTH_ENABLED=false` dev bypass

`api/app/dependencies/roles.py` still has `if not settings.auth_enabled: return "admin"`. This was considered for removal but kept because:

- It is a valid dev-only escape hatch, not a disabled production feature
- The production validator raises if `AUTH_ENABLED=false` is set in production/staging
- Removing it would require devs to provision real JWTs for local testing

No change made. The comment in `config.py` was updated from "feature flag fallback" to "dev-only; rejected in production by validator" to reduce ambiguity.

### Retained: `redis_allow_request` in `fairbet_runtime.py`

The function is still used by `api/app/services/entry_rate_limit.py` for pool entry abuse prevention. Only the unused import in `rate_limit.py` was removed.

---

## Sanity Check

```
# Confirm no remaining references to removed symbols
grep -r "fairbet_cursor_enabled\|fairbet_light_default_enabled\|fairbet_redis_limiter_enabled\|fairbet_odds_limiter_requests\|fairbet_odds_limiter_window\|resend_api_key\|_build_base_filters" api/
```

Expected: zero results (excluding this audit file).
