# Security Audit Report

**Date:** 2026-03-25
**Scope:** Full codebase — backend, frontend, infrastructure, auth, data flow

---

## A. Repository Understanding Summary

**Purpose:** Centralized sports data hub — automated ingestion, normalization, analytics/simulation, and serving of sports data (NBA, NHL, NCAAB, MLB, NFL) for downstream Dock108 apps.

**Components:**
- FastAPI backend (`api/`) — REST API, analytics engine, ML models, Celery tasks
- Next.js admin UI (`web/`) — internal admin dashboard
- Scraper (`scraper/`) — Celery workers for data ingestion
- Infrastructure (`infra/`) — Docker Compose, Caddy reverse proxy

**Key trust boundaries:**
1. **Public internet → Caddy → FastAPI** — API key required on all endpoints (except `/healthz`, `/auth/*`)
2. **Public internet → Caddy → Next.js → FastAPI** — admin UI behind basic auth, API key injected server-side
3. **Browser → Next.js proxy → FastAPI** — browser never sees API key
4. **Celery workers → PostgreSQL/Redis** — internal, no auth beyond connection credentials
5. **Downstream apps → FastAPI** — API key authentication, no per-user authorization

**Major security assumptions:**
- Single API key shared across all downstream consumers (no per-app isolation)
- Admin UI protected by basic auth at the Next.js layer, not JWT RBAC
- ML model artifacts loaded from filesystem via pickle/joblib (trusted paths)
- Rate limiting is in-memory (single instance only)

---

## B. Findings Table

| # | Finding | Severity | Category | Status |
|---|---------|----------|----------|--------|
| 1 | Pickle/joblib deserialization without integrity checks | High | Code Execution | **Fixed** — HMAC signing on save, verification on load |
| 2 | Auth endpoints use global rate limit (120/min) | Medium | Brute Force | **Fixed** — stricter per-endpoint limits (10/min) |
| 3 | API key in WebSocket/SSE query parameters | Medium | Credential Exposure | Open |
| 4 | Default JWT secret in dev config | Medium | Auth | **Fixed** — production validation added |
| 5 | Admin routes use API key only, no RBAC | Medium | Authorization | Accepted — documented design choice |
| 6 | Missing security headers | Medium | Browser Security | **Fixed** — added to Caddyfile |
| 7 | Model loader path traversal | Medium | Path Traversal | **Fixed** — canonical path + symlink check |
| 8 | Full stack traces stored in database | Low | Information Disclosure | Open |
| 9 | FastAPI docs exposed in production | Low | Information Disclosure | Acceptable — behind API key |
| 10 | CORS allows all methods/headers | Low | Transport | Acceptable — needed for REST API |
| 11 | Admin pages indexable by search engines | Low | Information Disclosure | **Fixed** — noindex added |
| 12 | In-memory rate limiter won't scale | Low | Availability | Open — needs Redis for multi-instance |
| 13 | SQL string formatting in migrations | Informational | SQL Injection | Acceptable — hardcoded inputs only |
| 14 | No email verification on signup | Informational | Account Abuse | Open — product decision |
| 15 | No session invalidation on password change | Informational | Auth | Open — acceptable for current scale |

---

## C. Detailed Findings

### 1. Pickle/Joblib Deserialization Without Integrity Checks

**Category:** Code Execution
**Severity:** High
**Confidence:** High
**Affected:** `api/app/analytics/models/core/model_loader.py`

**Why it matters:** `pickle.load()` and `joblib.load()` execute arbitrary Python bytecode during deserialization. If an attacker can control the file path (via model registry DB entry) or replace a model file on disk, they achieve remote code execution.

**Realistic exploit:** An attacker with database write access (SQL injection, compromised admin, or direct DB access) modifies `artifact_path` in the model registry to point to a crafted pickle file. The next simulation or inference call loads and executes the payload.

**Evidence:**
- `model_loader.py:54` — `joblib.load(path)`
- `model_loader.py:59` — `pickle.load(f)` with `# noqa: S301` suppression
- `inference_cache.py:52` — `joblib.load(path)`
- `_simulation_helpers.py:334` — `joblib.load(artifact_path)`

**Implemented mitigations:**
- Path validation: canonical path resolution + symlink rejection (model_loader.py)
- HMAC-SHA256 signing: artifacts are signed on save via `artifact_signing.sign_artifact()` in the training pipeline and calibrator
- HMAC verification: `ModelLoader.load_model()` verifies signature before deserialization
- Backward compatibility: unsigned pre-existing artifacts are allowed with a warning (no `.sig` file)
- Key source: `MODEL_SIGNING_KEY` env var (falls back to `API_KEY`)

**Remaining work:**
- Re-sign all existing model artifacts
- Long-term: evaluate ONNX or safetensors format instead of pickle

**Classification:** Mitigated. HMAC verification prevents tampered artifacts from being loaded. Unsigned legacy artifacts produce warnings in logs.

---

### 2. Auth Endpoints Use Global Rate Limit

**Category:** Brute Force
**Severity:** Medium
**Confidence:** High
**Affected:** `api/app/middleware/rate_limit.py`

**Why it matters:** `/auth/login` shares the same 120 requests/60 seconds limit as all other endpoints. An attacker can attempt 120 password guesses per minute per IP.

**Evidence:** `rate_limit.py:15` — `_EXEMPT_PREFIXES = ("/v1/sse", "/auth/me")`. Auth endpoints like `/auth/login`, `/auth/signup`, `/auth/forgot-password` get the default global limit.

**Implemented fix:** Auth-specific rate limiting tier added to `RateLimitMiddleware`. Auth endpoints (`/auth/login`, `/auth/signup`, `/auth/forgot-password`, `/auth/magic-link`, `/auth/reset-password`) are limited to 10 requests per 60 seconds per IP, separate from the global 120/min limit. Returns `429` with `Retry-After` header.

**Remaining work:** Redis-backed rate limiter for multi-instance deployments.

---

### 3. API Key in WebSocket/SSE Query Parameters

**Category:** Credential Exposure
**Severity:** Medium
**Confidence:** High
**Affected:** `api/app/realtime/auth.py:38-50`

**Why it matters:** Query parameters appear in HTTP access logs, browser history, proxy logs, and referrer headers. Passing the API key as `?api_key=...` risks leaking it.

**Evidence:**
```python
api_key = (
    websocket.query_params.get("api_key")
    or websocket.headers.get("x-api-key")
)
```

**Mitigating factor:** WebSocket connections can't use custom headers from browsers, so query params are a common pattern. The API key is injected server-side by the Next.js proxy, so browsers don't construct this URL directly.

**Recommended fix:** For WebSocket, accept API key as the first message after connection (auth handshake) instead of query param. For SSE, prefer header-only. If query params must stay, ensure Caddy/proxies do not log query strings for these paths.

---

### 4. Default JWT Secret in Dev Config — FIXED

**Severity:** Medium → **Resolved**

Added production validation that rejects the default `"dev-jwt-secret-change-in-production"` value and enforces minimum 32-character length.

---

### 5. Admin Routes Use API Key Only, No RBAC

**Category:** Authorization
**Severity:** Medium
**Confidence:** High
**Affected:** `api/main.py:150-191`

**Why it matters:** All admin endpoints (pipeline management, user CRUD, bulk operations) require only the shared API key — not an admin JWT role. Any downstream app with the API key can trigger admin operations.

**Evidence:** `main.py` registers admin routers with `dependencies=auth_dependency` (API key only), not `admin_dependency` (API key + `require_admin`).

**Current mitigation:** The admin UI is behind basic auth at the Next.js proxy layer. Downstream apps that only have the API key would need to know the admin route paths.

**Classification:** Intentional design choice. Acceptable for current deployment (single operator, single server) but should be hardened before multi-tenant or multi-consumer expansion.

---

### 6. Missing Security Headers — FIXED

**Severity:** Medium → **Resolved**

Added to Caddyfile: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `-Server` (strip server identifier).

---

### 7. Model Loader Path Traversal — FIXED

**Severity:** Medium → **Resolved**

Added canonical path resolution (`os.path.realpath + os.path.abspath`), symlink rejection, and audit logging to `ModelLoader.load_model()`.

---

### 8. Full Stack Traces Stored in Database

**Category:** Information Disclosure
**Severity:** Low
**Confidence:** High
**Affected:** `api/app/tasks/batch_sim_tasks.py:94`, `training_tasks.py`, `experiment_tasks.py`, `replay_tasks.py`

**Why it matters:** Full Python tracebacks (including file paths, local variable names, and potentially connection strings) are stored in database `error_message` fields and returned via API.

**Evidence:**
```python
job.error_message = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
```

**Recommended fix:** Truncate to exception type and message only. Store full traceback in structured logs, not the database. Redact paths in error messages returned via API.

---

### 9. FastAPI Docs Exposed in Production

**Category:** Information Disclosure
**Severity:** Low
**Confidence:** High
**Affected:** `infra/Caddyfile:33-39`

**Classification:** Acceptable. `/docs` and `/openapi.json` are routed through Caddy but require API key authentication at the FastAPI layer. This is useful for debugging and API exploration by authorized consumers.

---

### 10. CORS Allows All Methods/Headers

**Category:** Transport Security
**Severity:** Low
**Confidence:** Medium
**Affected:** `api/main.py:94-100`

**Classification:** Acceptable. `allow_methods=["*"]` and `allow_headers=["*"]` are common for REST APIs that serve multiple client types. Origins are properly whitelisted. Production validation ensures no localhost origins.

---

### 11. Admin Pages Indexable — FIXED

**Severity:** Low → **Resolved**

Added `<meta name="robots" content="noindex, nofollow" />` to admin layout.

---

### 12. In-Memory Rate Limiter Won't Scale

**Category:** Availability
**Severity:** Low
**Confidence:** High
**Affected:** `api/app/middleware/rate_limit.py`

**Why it matters:** The sliding-window rate limiter uses `defaultdict(deque)` in process memory. Multiple API server instances each maintain independent counters, effectively multiplying the rate limit by instance count.

**Classification:** Acceptable for current single-instance deployment. Needs Redis-backed limiter before horizontal scaling.

---

### 13–15. Informational Items

**SQL in migrations** — f-string SQL in seed migrations uses only hardcoded values. Not exploitable.

**No email verification** — Product decision. Accounts are immediately active. Low risk given admin-controlled environment.

**No session invalidation on password change** — JWTs remain valid until expiry. Low risk given 24h default TTL.

---

## D. Safe Hardening Changes Implemented

| Change | File | Impact |
|--------|------|--------|
| Security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, -Server) | `infra/Caddyfile` | Prevents clickjacking, MIME sniffing, leaks |
| Model loader path validation (canonical path + symlink rejection + audit logging) | `api/app/analytics/models/core/model_loader.py` | Prevents path traversal attacks |
| HMAC-SHA256 artifact signing on save | `api/app/analytics/training/core/training_pipeline.py`, `api/app/analytics/calibration/calibrator.py` | Signs artifacts at creation time |
| HMAC-SHA256 artifact verification on load | `api/app/analytics/models/core/model_loader.py` | Verifies integrity before deserialization |
| Artifact signing module | `api/app/analytics/models/core/artifact_signing.py` | `sign_artifact()` / `verify_artifact()` with constant-time comparison |
| Auth-specific rate limiting (10 req/min for login, signup, forgot-password, magic-link, reset) | `api/app/middleware/rate_limit.py` | Prevents brute-force on auth endpoints |
| JWT secret production validation (reject default, enforce 32+ chars) | `api/app/config.py` | Prevents deploying with dev secret |
| Admin noindex meta tag | `web/src/app/admin/layout.tsx` | Prevents search engine indexing |

---

## E. Remediation Roadmap

### Immediate (this sprint)

| # | Item | Complexity | Risk | Owner |
|---|------|-----------|------|-------|
| 1 | Stricter auth endpoint rate limits (10/min login, 5/min forgot-password) | Small | Low | Backend |
| 2 | Truncate stack traces in DB error fields; keep full traces in logs only | Small | Low | Backend |
| 3 | Restrict model loader to whitelisted directory paths | Small | Low | Backend |

### Before Wider Release

| # | Item | Complexity | Risk | Owner |
|---|------|-----------|------|-------|
| 4 | Add HMAC signature verification for model artifacts before pickle/joblib load | Medium | Medium | Backend/ML |
| 5 | Move WebSocket API key from query param to auth handshake message | Medium | Medium | Backend |
| 6 | Add per-API-key rate limiting for expensive simulation endpoints | Medium | Low | Backend |

### Medium-Term Hardening

| # | Item | Complexity | Risk | Owner |
|---|------|-----------|------|-------|
| 7 | Redis-backed rate limiter for multi-instance deployment | Medium | Low | Platform |
| 8 | Add RBAC enforcement on admin routes (require_admin dependency) | Medium | Medium | Backend |
| 9 | Add Content-Security-Policy header (requires testing with all frontend features) | Medium | Medium | Frontend/Platform |
| 10 | Per-service API keys (separate keys for downstream apps vs admin) | Medium | Low | Platform |

### Long-Term / Strategic

| # | Item | Complexity | Risk | Owner |
|---|------|-----------|------|-------|
| 11 | Evaluate ONNX/safetensors format to eliminate pickle deserialization entirely | Large | Low | ML/Backend |
| 12 | Add email verification flow on signup | Medium | Low | Product/Backend |
| 13 | Implement JWT token revocation (blacklist on password change) | Medium | Medium | Backend |
| 14 | Add audit logging for admin operations (who did what, when) | Medium | Low | Backend |
| 15 | Dependency vulnerability scanning in CI (Dependabot/Snyk) | Small | Low | DevOps |

---

## F. Security Testing Recommendations

**Unit/integration tests to add:**
- Test that model loader rejects paths outside whitelisted directories
- Test that model loader rejects symlinks
- Test that JWT with default secret is rejected in production config
- Test that auth endpoints return 429 under rate limit pressure
- Test that admin endpoints reject requests without valid API key

**CI gates to add:**
- `bandit` scan for Python security issues (pickle, eval, SQL injection patterns)
- `npm audit` / `yarn audit` for frontend dependency vulnerabilities
- `pip-audit` for Python dependency vulnerabilities
- Secret scanning (trufflehog or gitleaks) on every PR
- SAST integration (Semgrep rules for FastAPI/SQLAlchemy patterns)

**Manual verification needed:**
- Verify `.env` file is not present in any git history (not just current `.gitignore`)
- Verify production server uses unique passwords for each service
- Verify Caddy access logs do not capture query strings for `/v1/ws` and `/v1/sse` paths

---

## G. Leadership Summary

**Biggest actual risks:**
1. **Pickle deserialization** — achieves code execution if model paths are compromised. Path validation was added in this audit; HMAC signing should follow.
2. **Auth brute force** — login endpoint allows 120 attempts/min. Needs tighter per-endpoint limits.
3. **Single API key** — one key for all consumers means no isolation. A leaked key grants full access including admin operations.

**What is already reasonably good:**
- API key authentication with constant-time comparison
- Bcrypt password hashing
- Server-side API key injection (browser never sees it)
- Account enumeration protection on password reset/magic link
- Production config validation (CORS, API key length)
- Structured logging with sensitive parameter redaction
- No XSS, no command injection, no SSRF, no SQL injection in application code

**Fix before broader exposure:**
- Stricter auth rate limits (#1 above)
- Model artifact integrity verification (#4 above)
- WebSocket auth handshake instead of query param key (#5 above)

**Phase in later:**
- Redis-backed rate limiter, per-service API keys, RBAC on admin routes, CSP header, audit logging, JWT revocation
