# Security Audit — sports-data-admin

**Date:** 2026-04-22
**Scope:** FastAPI backend (`api/`), Celery scraper (`scraper/`), Next.js web UI (`web/`), infra/CI, dependencies
**Method:** Code inspection of auth, authz, input validation, middleware, logging, secrets, webhooks, XSS/CSRF, SSRF, deserialization, and dependency surface. Findings cite file + line.

Overall posture is **strong**. No critical or high-severity vulnerabilities were confirmed. The bulk of this report is hardening opportunities and notes on intentional patterns.

---

## 1. Confirmed vulnerabilities

### 1.1 Information disclosure on unauthenticated pool read
- **Severity:** Low (arguably intentional — see §3.1; flagged here because the exposure is not gated and not documented on the endpoint).
- **Evidence:** `api/app/routers/golf/pools.py:83-89` — `GET /pools/{pool_id}` has no auth dependency and `pools_helpers.py:178-182` fetches by ID with no tenancy filter.
- **Exploit:** Any internet caller can enumerate monotonic integer pool IDs and read pool metadata across all clubs without authentication (club name leakage, pool config, entry counts).
- **Fix (if unintentional):** Move to `/public/pools/{slug}` with an opaque slug, or require club-scoped auth. **If intentional** (public marketing/entry pages) add a slug-based route and drop the numeric-ID path to prevent enumeration; at minimum rate-limit this path strictly.
- **Status:** Needs product decision — see §3.1.

### 1.2 Permissive CSP on web UI (`unsafe-inline` for scripts)
- **Severity:** Medium.
- **Evidence:** `web/next.config.ts:23` — `script-src 'self' 'unsafe-inline' https://platform.twitter.com`.
- **Risk:** Any reflected/stored XSS in the Next.js UI is not mitigated by CSP — `'unsafe-inline'` allows arbitrary injected inline scripts to execute. Next.js generates inline bootstrap scripts, which is the usual reason this is set, but the blast radius is full XSS execution on the admin UI.
- **Exploit scenario:** A pool name or club description rendered unescaped into the DOM (even one leak in one component) becomes a full account-takeover vector against signed-in admins, since CSP is not a backstop.
- **Fix:** Switch to nonce-based CSP. Next.js 14+ supports `<Script nonce={nonce}>` via the app router. Generate a per-request nonce in `middleware.ts`, stamp it on `<script>` tags, and replace `'unsafe-inline'` with `'nonce-<value>'`. This is a common Next.js hardening pattern.

### 1.3 No commentary
_None found beyond 1.1 / 1.2._

---

## 2. Risky patterns / hardening opportunities

### 2.1 `ast.literal_eval` on admin review payload — **FIXED IN THIS AUDIT**
- **Severity:** Low (admin-only, data originates from tier1 validator, not end users).
- **Evidence:** `api/app/routers/admin/quality_review.py:81`.
- **Context:** `literal_eval` is _not_ `eval` — it only parses Python literals and cannot execute arbitrary code. However the bare `except Exception` and lack of return-type validation meant a malformed DB row could return unexpected types (dict, set) from this helper.
- **Change applied:** Tightened exception scope to `(ValueError, SyntaxError, MemoryError, RecursionError)` and added a return-type guard that coerces only `list|tuple` of `str`.

### 2.2 API key accepted in query string for WS/SSE
- **Severity:** Low.
- **Evidence:** `api/app/realtime/auth.py:38-41, 48-51` — both `verify_ws_api_key` and `verify_sse_api_key` accept `?api_key=…`.
- **Risk:** Query strings appear in reverse-proxy access logs, browser history, and `Referer` headers on same-origin subresource requests. The `secrets.compare_digest` check is safe against timing attacks, but the key may be written to nginx/caddy logs in plaintext.
- **Fix:** Require the `X-API-Key` header exclusively. If a query-string fallback is needed for EventSource (which cannot set custom headers), restrict it to SSE only, strip the `api_key` param from access logs at the proxy (or scrub it in the app's logging middleware — currently scrubbed in `middleware/logging.py:30-41`, which is good, but the edge proxy should also redact).

### 2.3 Unbounded Prometheus label cardinality on `path`
- **Severity:** Low (availability/observability).
- **Evidence:** `api/app/middleware/logging.py:92-93` — `http_requests_total.labels(method=method, path=path, status=status).inc()` uses `request.url.path` directly.
- **Risk:** Any route with path params (e.g. `/api/golf/pools/{pool_id}`) produces one label series per ID. An attacker (or a crawler) hitting `/api/golf/pools/1`, `/2`, `/3` … causes unbounded metric growth → memory bloat on the API pod and Prometheus.
- **Fix:** Use the matched route template (`request.scope.get("route").path` when available) or a normalizer that replaces numeric/UUID segments with `:id`.

### 2.4 `allow_headers` does not expose `X-Request-ID`
- **Severity:** Informational.
- **Evidence:** `api/main.py:191` — CORS `allow_headers=["Authorization","Content-Type","X-API-Key"]`.
- **Impact:** The middleware returns `X-Request-ID` in the response (`middleware/logging.py:83`) but browsers cannot read cross-origin response headers unless they're in `expose_headers`. Correlation in the web UI will silently fall back to client-generated IDs.
- **Fix:** Add `expose_headers=["X-Request-ID"]` to the CORS middleware.

### 2.5 `X-XSS-Protection: 1; mode=block`
- **Severity:** Informational.
- **Evidence:** `web/next.config.ts:6`.
- **Note:** The `X-XSS-Protection` header is deprecated and ignored by modern browsers; in some legacy configurations it can introduce its own XSS vectors. Safe to remove — kept here for defense-in-depth on old IE/Edge only.

### 2.6 Default `ON CONFLICT DO NOTHING` on Stripe webhook events
- **Severity:** Informational (the current behavior is correct).
- **Evidence:** `api/app/routers/webhooks.py:41-45`.
- **Note:** Idempotency is enforced by inserting the Stripe `event.id` into `ProcessedStripeEvent` with `ON CONFLICT DO NOTHING`. Signature is verified against the raw body (`webhooks.py:229-231`) before any parsing — this is the correct order. No action required.

### 2.7 CSP on API responses may break `/docs` and `/redoc`
- **Severity:** Informational / operational.
- **Evidence:** `api/app/middleware/security_headers.py:22` — `default-src 'self'`.
- **Note:** FastAPI's default Swagger/ReDoc load from `cdn.jsdelivr.net`. With this CSP, browsers will block those assets in production. If `/docs` is intentionally disabled in prod (common), this is fine; otherwise either self-host the swagger assets or add an exception for `/docs` and `/redoc`.

### 2.8 Dev-mode auth bypass fallbacks
- **Evidence:** `api/app/dependencies/auth.py:37-49`, `api/app/dependencies/roles.py:190-191`, `api/app/realtime/auth.py:20-24`.
- **Note:** Three independent code paths short-circuit auth when `settings.api_key` is unset or `AUTH_ENABLED=false`. All three are **correctly gated** on `environment not in {"production","staging"}` (or the config validator, `api/app/config.py:208-213`, refuses to boot with such settings in prod). Good. Recommend a single helper `is_auth_bypass_allowed()` to reduce the chance of a future regression adding a fourth bypass without the environment check.

### 2.9 Pool-ID enumeration via integer sequence
- See §1.1. Even if the endpoint is intentionally public, the numeric primary key leaks activity volume ("we're on pool 1,432") and enables scraping. Consider UUIDv7 / ULID public slugs.

---

## 3. Intentional / acceptable patterns worth documenting

### 3.1 Unauthenticated public pool read
- `api/app/routers/golf/pools.py:83-89` is very likely intentional — the roadmap (`ROADMAP.md` Phase 5 "Public Entry") explicitly covers path-based public pool landing pages. Document this on the endpoint docstring and the OpenAPI tag so future auditors don't re-flag it; ideally switch the public surface to opaque slugs (§2.9).

### 3.2 Pickle deserialization of ML model artifacts
- `api/app/analytics/models/core/model_loader.py:79` — `pickle.load` is gated by a prior HMAC-SHA256 `verify_artifact()` call on the canonical on-disk file, plus symlink and path-traversal checks. This is a correct pattern for trusted-source pickle; the `# noqa: S301` is deserved.

### 3.3 Environment-gated auth bypass in dev
- See §2.8. The bypass is a well-documented dev ergonomics choice, reinforced by a config validator that fails boot in staging/prod. Acceptable.

### 3.4 SQL parameterization and SQL-interpolation linter
- `scripts/lint_sql_interpolation.py` is wired into CI (`.github/workflows/backend-ci-cd.yml`) and catches f-strings, `%`, and `.format()` inside `text()` / `execute()`. Combined with ORM-everywhere usage (`routers/golf/pools_helpers.py`, `services/audit.py`, `routers/webhooks.py` all use parameterized constructs), SQLi surface is effectively zero.

### 3.5 Stripe webhook pattern
- Raw-body signature verification → idempotent insert on `processed_stripe_events` → parameterized updates. Textbook-correct.

### 3.6 Structured log redaction
- `api/app/logging_config.py:13-24` and `api/app/middleware/logging.py:29-41` scrub `token`, `authorization`, `password`, `api_key`, `secret`, `signature`, etc. from both log extras and query strings, with value truncation. Good coverage.

### 3.7 Secure-by-default Docker images
- `infra/api.Dockerfile` and `web.Dockerfile` run as non-root UIDs, multi-stage builds, production-only deps. `docker-compose.yml` scopes DB/Redis to an internal bridge network. No credentials baked into images.

### 3.8 CI workflow hygiene
- `.github/workflows/backend-ci-cd.yml` does not use `pull_request_target` with untrusted checkout; secrets are scoped to the deploy job; no `${{ github.event.* }}` values interpolated into shell commands (which would be a script-injection sink).

### 3.9 HTML sanitization helper
- `api/app/utils/sanitize.py` uses `bleach.clean(value, tags=[], attributes={}, strip=True)` for free-text fields. This is the correct strict-strip configuration — bleach will html-encode anything that isn't in the allowlist, and the allowlist is empty.

---

## 4. Items needing manual verification

1. **Reverse proxy log scrubbing.** The app scrubs `api_key` from its own structured logs, but if nginx/Caddy/ALB logs are shipped separately, confirm the `api_key` query parameter is not captured there (§2.2). Check `infra/` and deployment runbook.
2. **`/docs` exposure in production.** Confirm whether FastAPI `/docs` and `/redoc` are disabled in prod (via `docs_url=None`). If not, §2.7 will break them — and they'd also be leaking the full schema to unauthenticated clients.
3. **Admin Origin/X-Forwarded-Origin trust.** `api/app/dependencies/roles.py:158` appears to resolve role context partially from `Origin` / `X-Forwarded-Origin` headers. Verify the edge proxy strips `X-Forwarded-*` on inbound public traffic so a crafted header cannot promote a user to admin. (Could not fully verify without nginx/Caddy config in this repo.)
4. **JWT refresh / revocation.** Spot-checked login/signup paths; did not fully audit refresh-token rotation and revocation on logout. Worth a follow-up focused pass.
5. **Subdomain routing regex.** `settings.cors_origin_regex` (`api/app/config.py:142-166`) is trusted at runtime. Verify the regex is anchored (`^…$`) and restricts to the expected TLD; an unanchored regex accepting `evil.com.yourdomain.fake` would let attackers send credentialed CORS requests.
6. **Public pool endpoint rate limiting.** Confirm the unauthenticated `GET /pools/{pool_id}` falls under the global per-IP tier rather than a laxer unauthenticated tier.

---

## 5. Changes applied in this audit

- `api/app/routers/admin/quality_review.py` — narrowed exception scope around `ast.literal_eval` and added return-type validation (§2.1). Non-functional for valid payloads; rejects malformed DB rows cleanly instead of propagating exotic types.

No other code changes were made. Findings in §1 and §2 are left for product/engineering decisions.

---

## 6. Recommended follow-up priority

| # | Item | Effort | Impact |
|---|---|---|---|
| 1 | Remove `'unsafe-inline'` from web CSP; adopt nonces (§1.2) | M | High |
| 2 | Decide on public pool endpoint — slug-based or auth-gated (§1.1, §2.9) | S | Med |
| 3 | Normalize Prometheus `path` label (§2.3) | S | Med (availability) |
| 4 | Drop `api_key` query-param fallback or scope to SSE only (§2.2) | S | Low |
| 5 | Add `expose_headers=["X-Request-ID"]` to CORS (§2.4) | XS | Low |
| 6 | Verify items in §4 (ops/edge configuration) | M | High if misconfigured |
