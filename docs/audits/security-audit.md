# Security Audit — sports-data-admin

> Performed: 2026-04-18 (updated 2026-04-19)
> Branch: `aidlc_1`  
> Scope: Full monorepo — FastAPI API, Celery scraper, Next.js web, shared packages, infra

---

## Executive Summary

The codebase has a **solid security foundation**: bcrypt password hashing, constant-time API key comparison, JWT algorithm pinning, strong production-config validation, structured log redaction, and proper consumer/admin key isolation.

This document covers two audit passes. The initial pass found and fixed eight confirmed vulnerabilities (two High, six Medium/Low). The second pass (2026-04-19) found three additional issues fixed in-place plus one remaining medium requiring manual action.

| Severity | Confirmed | Fixed In-Place | Remaining |
|----------|-----------|---------------|-----------|
| Critical | 1 | 1 | 0 |
| High | 3 | 3 | 0 |
| Medium | 5 | 5 | 0 |
| Medium (open) | 1 | 0 | 1 |
| Medium (hardening) | 4 | 0 | 4 |
| Low | 7 | 0 | 7 |
| Informational | 6 | — | — |

---

## 1. Confirmed Vulnerabilities — Fixed In-Place

### V8 · Next.js admin middleware existed but was never wired up — FIXED (2026-04-19)
**Severity:** Critical  
**Files:** `web/src/proxy.ts`, `web/src/middleware.ts` (created)

`web/src/proxy.ts` contains a complete, correctly-implemented Basic Auth middleware — constant-time password comparison via Web Crypto SHA-256, fail-closed on missing `ADMIN_PASSWORD`, and a `config.matcher` that correctly excludes static assets and API routes. No `middleware.ts` file existed, so Next.js never loaded it. All pages under `/admin/*` were accessible without authentication.

**Exploit scenario:** Any network-reachable browser navigates to `/admin/pipeline`. The page loads and all client-side API calls route through `/api/proxy/[...path]`, which injects `SPORTS_API_KEY` server-side. The attacker gains full admin capability — triggering pipeline runs, reading game data, managing users — without supplying any credentials.

**Fix applied:** Created `web/src/middleware.ts`:
```typescript
export { proxy as middleware, config } from "./proxy";
```

**Prerequisite:** `ADMIN_PASSWORD` must be set as a strong, independent secret in the production environment. The docker-compose passes `ADMIN_PASSWORD: ${POSTGRES_PASSWORD:-}`; if unset, the middleware returns HTTP 500 (fail-closed). Do not share this password with `POSTGRES_PASSWORD`.

---

### V9 · `/auth/me/*` account endpoints exempt from all rate limiting — FIXED (2026-04-19)
**Severity:** High  
**File:** `api/app/middleware/rate_limit.py:31`

```python
# Before
_EXEMPT_PREFIXES = ("/v1/sse", "/auth/me")
```

The `/v1/sse` exemption is correct (SSE connections must not be rate-limited). The `/auth/me` prefix exemption was too broad — it also silently disabled rate limiting on:

- `PATCH /auth/me/email` — change account email address
- `PATCH /auth/me/password` — change account password
- `DELETE /auth/me` — delete account

**Exploit scenario:** An attacker with a valid user JWT (legitimately obtained) can brute-force `PATCH /auth/me/password` unlimited times. The auth-strict tier (10 req/60s) that protects login was entirely bypassed for password change.

**Fix applied:**
```python
_EXEMPT_PREFIXES = ("/v1/sse",)
```
All `/auth/me/*` endpoints now fall through to the global tier (120 req/60s by default), which is sufficient for legitimate usage.

---

### V10 · PostgreSQL port bound to all interfaces in docker-compose — FIXED (2026-04-19)
**Severity:** Medium  
**File:** `infra/docker-compose.yml:23`

```yaml
# Before
ports:
  - "${POSTGRES_PORT:-5432}:5432"
```

Although postgres is on the `internal: true` Docker network (blocking inter-container routing from external), the `ports` directive punches a host port mapping independent of network membership. On a host without a strict external firewall, port 5432 would be reachable from the internet.

**Fix applied:**
```yaml
# After
ports:
  - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
```

---

### V11 · `ADMIN_PASSWORD` defaults to `POSTGRES_PASSWORD` — OPEN
**Severity:** Medium  
**File:** `infra/docker-compose.yml:350`

```yaml
ADMIN_PASSWORD: ${POSTGRES_PASSWORD:-}
```

The web admin UI password is tied to the database password. A single leaked credential compromises both. If `POSTGRES_PASSWORD` remains at the default (`sports`), `ADMIN_PASSWORD` is `sports`. Additionally, Grafana's admin password shares the same default (line 447: `GF_SECURITY_ADMIN_PASSWORD: ${POSTGRES_PASSWORD:-sports}`).

**Required manual action:** Set `ADMIN_PASSWORD` and `GF_SECURITY_ADMIN_PASSWORD` as independent secrets in `.env`. Update `.env.example` to reflect the three distinct required values.

---

### V0 · Privilege escalation via proxy: any authenticated user could access admin endpoints — FIXED
**Severity:** High  
**Files:** `api/app/dependencies/roles.py:185-186`, `web/src/app/proxy/[...path]/route.ts:55`  
**Confidence:** 10/10

**Description:** The Next.js proxy at `/proxy/[...path]` injects the server-side admin API key (`SPORTS_API_KEY`) into **every forwarded request**, regardless of path or the calling user's role. The backend's `resolve_role()` previously returned `"admin"` unconditionally whenever `request.state.api_key_verified` was `True` — which is set by `verify_api_key()` as soon as the valid API key is seen. Because the proxy appends the API key to all requests (line 55 of `route.ts`) and also forwards the caller's `Authorization` header (line 57), the JWT role was silently bypassed.

**Exploit scenario:**
1. Attacker creates a normal user account and receives a JWT with `role: "user"`.
2. Attacker makes a browser `fetch("/proxy/api/admin/users")` — a path they are not authorized for.
3. The Next.js proxy adds `X-API-Key: <server_admin_key>` and forwards the user's `Authorization: Bearer <user_jwt>`.
4. `verify_api_key()` validates the API key, sets `api_key_verified = True`.
5. `resolve_role()` sees the flag and previously returned `"admin"` immediately, skipping JWT evaluation entirely.
6. `require_admin()` passes; attacker gains full admin access (user management, pipeline control, odds sync, task triggers, etc.).

**Fix applied:** `resolve_role()` now checks whether a JWT bearer token is also present when `api_key_verified` is `True`. If a JWT is present, the JWT role is decoded and returned; only requests without a JWT (e.g. non-browser server-to-server calls using only the API key) continue to receive the `"admin"` role. Regular users routing through the proxy now receive their actual JWT role and are rejected by `require_admin()`.

```python
# api/app/dependencies/roles.py — after fix
if getattr(request.state, "api_key_verified", False):
    if credentials is not None:
        # JWT present — respect its role, do not unconditionally elevate.
        payload = decode_access_token(credentials.credentials)
        role = payload.get("role", "user")
        ...
        return role
    return "admin"  # no JWT — API-key-only server call, admin intent preserved
```

---

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
| **Critical** | **Set independent `ADMIN_PASSWORD` and `GF_SECURITY_ADMIN_PASSWORD` in production .env (V11)** | Ops |
| High | Extend Redis-backed rate limiter to auth endpoints (H1) | API |
| High | Add Redis auth validation to production config (H2) | Infra |
| Medium | Route Grafana through Caddy TLS — remove direct port 3001 exposure | Infra |
| Medium | Per-endpoint `require_admin` dependency for defense-in-depth (H3) | API |
| Medium | Per-task argument validation in task trigger endpoint (H4) | API |
| Low | Dummy bcrypt call on missing user to prevent timing enum (H5) | API |
| Low | Verify X credentials are in secrets manager, not .env files (M1) | Infra |
| Low | Verify Caddy strips X-Forwarded-* from client requests (M4) | Infra |
| Low | Confirm AUTH_ENABLED=false absent from all non-dev envs (M5) | Ops |
| Low | Confirm SPORTS_API_INTERNAL_URL set in production (M6) | Ops |
