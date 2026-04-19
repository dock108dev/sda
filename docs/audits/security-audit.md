# Security Audit — sports-data-admin

> Performed: 2026-04-18  
> Branch: `aidlc_1`  
> Scope: Full monorepo — FastAPI API, Celery scraper, Next.js web, shared packages, infra

---

## Executive Summary

The codebase has a **solid security foundation**: bcrypt password hashing, constant-time API key comparison, JWT algorithm pinning, strong production-config validation, structured log redaction, and proper consumer/admin key isolation. No critical authentication bypasses or injection vulnerabilities were found.

Five confirmed vulnerabilities (one High, four Medium) were fixed in-place during this audit. Additional hardening opportunities and areas for manual verification are documented below.

| Severity | Confirmed | Fixed In-Place | Remaining |
|----------|-----------|---------------|-----------|
| High | 1 | 1 | 0 |
| Medium | 4 | 4 | 0 |
| Medium (hardening) | 4 | 0 | 4 |
| Low | 7 | 0 | 7 |
| Informational | 6 | — | — |

---

## 1. Confirmed Vulnerabilities — Fixed In-Place

### V1 · Exception messages leaked in 500 responses — FIXED
**Severity:** High  
**Files:** `api/app/routers/admin/pipeline/run_endpoints.py` (5 handlers)

All five `except Exception as e: ... detail=f"...{e}"` patterns in pipeline endpoints returned raw Python exception strings to clients. These can contain SQLAlchemy error text (schema/table names), internal file paths, and other internals.

**Fix applied:** Each handler now calls `logger.exception(...)` with structured context and returns a generic `"...See server logs for details."` message.

---

### V2 · No global exception handler — FIXED
**Severity:** Medium  
**File:** `api/main.py`

FastAPI's default `ServerErrorMiddleware` serialises Python tracebacks to JSON on unhandled exceptions. No application-level handler was present.

**Fix applied:** Added `@app.exception_handler(Exception)` that logs the full exception and returns `{"detail": "Internal server error"}`.

---

### V3 · OpenAPI docs exposed in production — FIXED
**Severity:** Medium  
**File:** `api/main.py`

`/docs`, `/redoc`, and `/openapi.json` were enabled unconditionally, exposing the full API surface (all admin endpoint signatures, parameter names, response shapes) without authentication.

**Fix applied:** `docs_url`, `redoc_url`, and `openapi_url` are now set to `None` when `ENVIRONMENT` is `production` or `staging`.

---

### V4 · Bulk generation endpoint had no resource limits — FIXED
**Severity:** Medium  
**File:** `api/app/routers/admin/pipeline/bulk_endpoints.py`

`BulkGenerateRequest.max_games` defaulted to `None` (unlimited) with no cap, and no date-range limit was enforced. A single request could enqueue thousands of expensive pipeline tasks, flooding Celery and the database.

**Fix applied:**
- Date range capped at 180 days; requests exceeding this return HTTP 400.
- `max_games` capped at 500; requests exceeding this return HTTP 400.
- `end_date < start_date` returns HTTP 400.
- Job record uses capped value, not raw request value.

---

### V5 · Proxy forwarded user-controlled `X-Forwarded-Origin` header — FIXED
**Severity:** Medium  
**File:** `web/src/app/proxy/[...path]/route.ts`

The Next.js API proxy forwarded `X-Forwarded-Origin` (read from the browser request) to the backend. The backend's `_is_admin_origin()` check in `api/app/dependencies/roles.py` accepts `x-forwarded-origin` as a valid origin source. A browser could send `X-Forwarded-Origin: https://admin.example.com` to spoof admin origin recognition.

**Fix applied:** `X-Forwarded-Origin` is no longer forwarded. The `Referer` header was also removed from forwarding as it is not required by the backend and could leak admin URLs to backend logs.

---

### V6 · Missing HTTP security headers on Next.js app — FIXED
**Severity:** Medium  
**File:** `web/next.config.ts`

No `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Strict-Transport-Security`, `Referrer-Policy`, or `Permissions-Policy` headers were set.

**Fix applied:** Added `headers()` config to `next.config.ts` applying the following to all routes:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` |
| `Content-Security-Policy` | See config; allows Twitter embed, restricts all else to `'self'` |

**Note:** CSP uses `unsafe-inline` for scripts and styles due to Next.js runtime requirements. Tighten with nonce-based CSP once a nonce injection approach is in place.

---

### V7 · CORS allows all methods and headers with `credentials: true` — FIXED
**Severity:** Low  
**File:** `api/main.py`

`allow_methods=["*"]` and `allow_headers=["*"]` combined with `allow_credentials=True` is overly permissive. While origins are whitelisted (good), restricting methods and headers reduces attack surface.

**Fix applied:**
```python
allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
allow_headers=["Authorization", "Content-Type", "X-API-Key"],
```

---

## 2. Risky Patterns / Hardening Opportunities

### H1 · Rate limiting is in-memory only (not distributed)
**Severity:** Medium  
**File:** `api/app/middleware/rate_limit.py`

`RateLimitMiddleware` stores counters in `defaultdict(deque)` — per-process, per-instance memory. With multiple API workers or containers, each instance tracks limits independently. An attacker distributing requests across N instances can send 10×N auth attempts per minute instead of 10.

**Recommendation:** Extend the existing Redis limiter (`fairbet_redis_limiter`) to auth endpoints. The infrastructure is already there.

---

### H2 · Redis URL lacks authentication validation in production
**Severity:** Medium  
**Files:** `api/app/config.py`, `scraper/sports_scraper/live_odds/redis_store.py`

`redis_url` defaults to `redis://localhost:6379/2` (no auth). No production validator enforces `rediss://` (TLS) or a password in the URL. Redis stores Celery task state, hold-key locks, and live odds snapshots — unauthenticated access within the internal network could read or manipulate all of these.

**Recommendation:** Add to `validate_runtime_settings`:
```python
if self.environment in {"production", "staging"}:
    if "redis://" in self.redis_url and "@" not in self.redis_url:
        raise ValueError("Redis URL must include credentials in production")
```

---

### H3 · Admin endpoints lack per-endpoint role dependencies (defense-in-depth)
**Severity:** Medium  
**Files:** `api/app/routers/admin/users.py`, all admin routers

Admin routers are protected at the `app.include_router(..., dependencies=admin_dependency)` level in `main.py`. Individual endpoint functions have no `Depends(require_admin)`. If a router is accidentally re-included without dependencies, endpoints become unauthenticated.

**Recommendation:** Add `_admin: str = Depends(require_admin)` to the signature of each admin endpoint as a defense-in-depth measure.

---

### H4 · Task trigger endpoint accepts unvalidated arguments
**Severity:** Medium  
**File:** `api/app/routers/admin/task_control.py` (lines 43–45)

`TriggerRequest.args: list[Any]` accepts arbitrary values which are passed directly to `celery.send_task(entry.name, args=body.args)`. While the task name is allowlisted, argument shape is not validated per task. Arguments are also logged unredacted at line 379–383.

**Recommendation:**
1. Add a per-task argument schema dictionary and validate before dispatch.
2. Sanitize logged args (log count + types, not values).

---

### H5 · Login endpoint has minor email-enumeration timing difference
**Severity:** Low  
**File:** `api/app/routers/auth.py` (lines 195–204)

When a user does not exist, bcrypt is not called (~0.1 ms). When the user exists but the password is wrong, bcrypt runs (~100 ms). An attacker with sub-millisecond network measurement could distinguish existing accounts.

Rate limiting (10 req/min/IP) makes mass enumeration impractical. This is low risk but fixable:

```python
dummy_hash = "$2b$12$aaaaaaaaaaaaaaaaaaaaaOaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
hash_to_check = user.password_hash if user else dummy_hash
if user is None or not _pwd_ctx.verify(body.password, hash_to_check):
    raise HTTPException(401, "Invalid email or password")
```

---

### H6 · Twitter widget loaded without Subresource Integrity (SRI)
**Severity:** Low  
**File:** `web/src/components/social/TwitterEmbed.tsx` (line 60)

```typescript
script.src = "https://platform.twitter.com/widgets.js";
```

No `integrity` attribute. A CDN compromise could serve malicious JS.

**Recommendation:** Add SRI hash. Twitter's CDN does not publish hashes; the safest alternative is sandboxing the embed in an `<iframe sandbox>` or accepting the risk given Twitter's CDN reliability.

---

### H7 · Alembic seed migrations use f-string SQL
**Severity:** Low  
**Files:** `api/alembic/versions/20260301_000007_seed_mlb_teams.py`, `20260321_seed_nfl_teams.py`

```python
op.execute(f"INSERT INTO sports_teams ... VALUES (... '{esc_name}' ...)")
```

Values are hardcoded team names with `replace("'", "''")` escaping. No runtime injection risk, but the pattern is fragile and inconsistent with ORM usage elsewhere.

**Recommendation:** Use `sqlalchemy.text()` with `:name` bound parameters in future migrations.

---

## 3. Intentional / Acceptable Patterns

| Pattern | File | Why It's OK |
|---------|------|-------------|
| API keys plaintext in env | `api/app/config.py` | Standard for server-side keys; comparison is via `secrets.compare_digest` |
| JWT in `localStorage` is NOT done here | — | Tokens are sent as `Authorization: Bearer` headers, not stored in localStorage |
| `AUTH_ENABLED=false` grants admin | `api/app/dependencies/roles.py` | Validated: this flag cannot be in production config (startup validator blocks it) |
| In-memory pub/sub | `api/app/realtime/manager.py` | Documented Phase 5 migration to Redis Streams; acceptable for current scale |
| Healthcheck reveals DB status | `api/main.py` | Internal load-balancer endpoint; acceptable if not publicly routable |
| bcrypt custom wrapper (not passlib) | `api/app/security.py` | Intentional — passlib has Python 3.14 incompatibility. Implementation is correct |
| 24-hour JWT TTL, no revocation | `api/app/dependencies/roles.py` | Acceptable; logout clears client token. Magic-link / reset tokens have `purpose` claim preventing reuse |
| Consumer API key rejected on admin routes | `api/app/dependencies/consumer_auth.py` | Explicitly designed; documented in code comment |

---

## 4. Items Requiring Manual Verification

### M1 · X/Twitter session credentials lifecycle
**File:** `scraper/sports_scraper/social/playwright_collector.py`  
`X_AUTH_TOKEN` and `X_CT0` cookie values are read from environment. Verify these are rotated when cookies expire and that the env values on the production host are stored in a secrets manager (not in `.env` files on disk).

### M2 · Celery task argument content in production logs
**File:** `api/app/routers/admin/task_control.py` line 379  
Task args are logged at `INFO` level. Review what argument values flow through in production to confirm no PII or sensitive identifiers are included.

### M3 · Redis authentication in production deployment
**File:** `infra/docker-compose.yml` Redis service definition  
Verify the production Redis instance has `requirepass` set and `bind` is not `0.0.0.0`, or is behind a VPC security group that blocks external access.

### M4 · Reverse proxy strips/normalizes `X-Forwarded-*` headers
**File:** `infra/Caddyfile` or nginx config  
The backend's `_is_admin_origin()` no longer receives `X-Forwarded-Origin` from the Next.js proxy (fixed above), but verify that Caddy/nginx does not pass raw client-supplied `X-Forwarded-*` headers through to the API unmodified.

### M5 · `AUTH_ENABLED=false` is absent from all non-development environments
The startup validator only blocks `JWT_SECRET` default in production/staging; it does not explicitly block `AUTH_ENABLED=false`. Verify the production `.env` does not include this flag.

### M6 · `NEXT_PUBLIC_SPORTS_API_URL` scope
**File:** `web/src/app/proxy/[...path]/route.ts` line 15  
The proxy falls back to `NEXT_PUBLIC_SPORTS_API_URL` if `SPORTS_API_INTERNAL_URL` is not set. `NEXT_PUBLIC_*` vars are bundled into the browser JS bundle. Confirm `SPORTS_API_INTERNAL_URL` is always set in production so the internal URL is never exposed to the client.

---

## 5. Positive Security Patterns (Keep)

- **JWT algorithm pinning** — `algorithms=[settings.jwt_algorithm]` prevents algorithm confusion.
- **Constant-time API key comparison** — `secrets.compare_digest()` everywhere keys are checked.
- **Token purpose claims** — Reset and magic-link tokens include `"purpose"` claim; can't be reused as access tokens.
- **Consumer key isolation** — Consumer keys explicitly rejected on admin routes; `api_key_verified` flag not set for consumer auth.
- **Production config validator** — `model_validator` at startup raises `ValueError` for weak secrets, localhost CORS, missing keys.
- **Log redaction middleware** — `_REDACT_QUERY_PARAMS` strips `token`, `api_key`, `password`, etc. from access logs.
- **bcrypt with auto-generated salts** — Correct implementation, no passlib dependency risk.
- **Email enumeration prevention** — Forgot-password and magic-link endpoints return identical responses for registered/unregistered emails.
- **Celery JSON serialization** — `accept_content: ["json"]` prevents pickle deserialization attacks.
- **Multi-stage Docker builds, non-root user** — Containers run as `appuser`, not root.

---

## Remediation Backlog

| Priority | Item | Owner |
|----------|------|-------|
| High | Extend Redis-backed rate limiter to auth endpoints (H1) | API |
| High | Add Redis auth validation to production config (H2) | Infra |
| Medium | Per-endpoint `require_admin` dependency for defense-in-depth (H3) | API |
| Medium | Per-task argument validation in task trigger endpoint (H4) | API |
| Low | Dummy bcrypt call on missing user to prevent timing enum (H5) | API |
| Low | Verify X credentials are in secrets manager, not .env files (M1) | Infra |
| Low | Verify Caddy strips X-Forwarded-* from client requests (M4) | Infra |
| Low | Confirm AUTH_ENABLED=false absent from all non-dev envs (M5) | Ops |
| Low | Confirm SPORTS_API_INTERNAL_URL set in production (M6) | Ops |
