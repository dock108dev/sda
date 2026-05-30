# Combined SDA / Scroll Down Security Review

Date: 2026-05-30
Scope: `sports-data-admin`, `scroll-down-web`, and `scroll-down-ios` reviewed as one backend + frontend + mobile system.

## A. Repository understanding summary

`sports-data-admin` is the SDA control plane: a FastAPI backend, Celery/scraper workers, PostgreSQL/Redis integration, and a Next.js admin UI. The active FastAPI surface in `api/main.py` mounts the consumer `/api/v1` router, the sports/social admin routers, and a smaller set of `/api/admin` operational routers. Auth, onboarding, commerce, billing, golf, odds, analytics, and webhook routers exist in the repo but are not mounted by the current `main.py`. Commerce/billing/Stripe surfaces are now explicitly deprecated and out of production-readiness scope; they should be removed rather than hardened.

`scroll-down-web` is the public Next.js app. It acts as a BFF over SDA: public API routes inject `X-API-Key` server-side and fetch SDA admin sports endpoints. It also has a local magic-link/session implementation, AI story generation routes, reveal/history sync APIs, analytics events, and client-side persistence for non-secret reading/reveal state.

`scroll-down-ios` is a SwiftUI client. It reads `SDABaseURL` and `SDAApiKey` from build-time `Info.plist` settings and currently calls SDA admin sports endpoints directly from the app.

Key trust boundaries:

- Anonymous browser to `scroll-down-web` public API routes.
- Public web BFF to SDA with server-side API key injection.
- iOS app bundle to SDA with an embedded build-time API key.
- Admin browser to SDA admin Next.js `/proxy/*`, which injects `SPORTS_API_KEY`.
- SDA FastAPI to PostgreSQL, Redis, Celery, OpenAI/email providers, and scraper jobs. Stripe references are deprecated and should be removed.
- Third-party callbacks/routes present in code but not mounted in current API entrypoint.

Major security assumptions:

- SDA `API_KEY` is an admin credential. `CONSUMER_API_KEY` exists but iOS and public web still use admin sports endpoints.
- Admin UI should be protected by Basic auth in production/staging and by backend API key injection.
- Production SDA should set `ALLOWED_CORS_ORIGINS`, strong `API_KEY`, strong `JWT_SECRET`, and `AUTH_ENABLED=true`; the config validator enforces these.
- Operational endpoints such as `/metrics`, `/healthz`, and `/ready` are acceptable only if exposure is controlled by the deployment layer.

## B. Findings table

| ID | Title | Category | Severity | Confidence | Status |
|---|---|---:|---:|---:|---|
| F1 | iOS embeds a key used against admin-scoped SDA endpoints | Auth / least privilege | High | High | Fix before broad mobile release |
| F2 | SDA admin web proxy allowed unauthenticated credential-injected proxy paths | Auth / proxy boundary | High | High | Fixed in this review |
| F3 | Public web used vulnerable Next.js 16.2.4 | Supply chain | High | High | Fixed in this review |
| F4 | Public web could log production magic links when email provider was unset | Secrets / auth token handling | Medium | High | Fixed in this review |
| F5 | Public web BFF exposes public endpoints backed by SDA admin sports routes | API boundary / abuse | Medium | High | Fix next |
| F6 | SDA `/metrics` is unauthenticated if the API service is internet reachable | Operational exposure | Medium | Medium | Verify deployment or protect |
| F7 | Backend reset-token JWTs are replayable if auth router is mounted | Auth recovery | Medium | Medium | Investigate before mounting auth |
| F8 | Deprecated commerce/Stripe code remains in the repo | Dead surface / removal | Low | High | Remove rather than harden |
| F9 | Structured logging redacts field names but not arbitrary exception strings | Logging / secrets | Low | Medium | Harden later |
| F10 | Broad ad/affiliate CSP on public web increases browser attack surface | Browser security | Low | High | Accept with monitoring |
| F11 | iOS local override file contains a private API key in this workspace | Secret hygiene | Informational | High | Rotate if shared; keep ignored |

## C. Detailed findings

### Confirmed meaningful vulnerabilities

#### F1. iOS embeds a key used against admin-scoped SDA endpoints

Category: authentication, authorization, secrets handling
Affected area: `scroll-down-ios` to SDA backend
Severity: High
Confidence: High
Disposition: Fix before broad mobile release

Why it matters: Mobile app bundle values are extractable. A key shipped in `Info.plist` must be treated as public. The iOS client currently calls `/api/admin/sports/games` and `/api/admin/sports/games/{id}` and sends `X-API-Key` when configured. SDA admin route dependencies validate this against the admin `API_KEY`, and passing that key marks the request as admin-authenticated.

Realistic exploit scenario: An attacker extracts `SDAApiKey` from a release build or device backup and uses it outside the app to call admin SDA endpoints, including operational endpoints mounted under `/api/admin` or `/api/admin/sports`.

Evidence:

- `scroll-down-ios/ScrollDownSports/Services/SDAApiClient.swift:49` builds `/api/admin/sports/games`.
- `scroll-down-ios/ScrollDownSports/Services/SDAApiClient.swift:72` builds `/api/admin/sports/games/{id}`.
- `scroll-down-ios/ScrollDownSports/Services/SDAApiClient.swift:87-89` sends `X-API-Key`.
- `scroll-down-ios/Config/Secrets.xcconfig:1-5` and `Info.plist` place `SDA_API_KEY` into app config.
- `sports-data-admin/api/main.py:121-188` mounts admin routers with `auth_dependency`.
- `sports-data-admin/api/app/dependencies/auth.py:83-100` validates the admin key and sets `request.state.api_key_verified`.

Recommended fix: Create a mobile/public read-only endpoint set under `/api/v1` that returns the game list/detail data the app actually needs. Require `CONSUMER_API_KEY`, reject admin keys on consumer routes, and stop shipping an admin key in iOS. If mobile access is intended to be open, remove the static shared secret model and rely on rate limiting, attestation if needed, and response minimization.

#### F2. SDA admin web proxy allowed unauthenticated credential-injected proxy paths

Category: authentication, proxy boundary
Affected area: `sports-data-admin/web`
Severity: High
Confidence: High
Disposition: Fixed now

Why it matters: The Next.js admin `/proxy/[...path]` route injects `SPORTS_API_KEY` server-side. Before this review, middleware protected only selected proxy prefixes, and a test explicitly allowed `/proxy/api/v1/games/123` through without Basic auth. Any unlisted backend path reachable through `/proxy/*` could be called by an unauthenticated browser with the admin web server's API key attached.

Realistic exploit scenario: An unauthenticated requester calls an unlisted `/proxy/...` path that is mounted now or added later. The proxy forwards the request to internal SDA and injects `X-API-Key`, bypassing the intended admin UI gate.

Evidence:

- Previous test behavior in `sports-data-admin/web/src/proxy.test.ts` allowed `/proxy/api/v1/games/123`.
- `sports-data-admin/web/src/app/proxy/[...path]/route.ts:55` injects `X-API-Key`.
- Fixed state: `sports-data-admin/web/src/proxy.ts:3-6` now protects all `/proxy`.

Recommended fix: Keep all `/proxy/*` behind admin auth and add regression tests for every credential-injecting proxy surface.

#### F3. Public web used vulnerable Next.js 16.2.4

Category: dependency and supply chain
Affected area: `scroll-down-web/web`
Severity: High
Confidence: High
Disposition: Fixed now

Why it matters: `npm audit --omit=dev --json` reported high-severity Next.js advisories for `next >=16.0.0 <16.2.5` and `<16.2.6`, including App Router proxy/middleware bypass and denial-of-service advisories. Public web was on `next 16.2.4`; SDA admin web was already on `16.2.6`.

Realistic exploit scenario: A public attacker targets a known Next.js App Router/proxy bypass or DoS class against the public web app.

Evidence:

- Before fix: `scroll-down-web/web/package.json` used `next 16.2.4`.
- Fixed state: `scroll-down-web/web/package.json:19-25` now uses `next 16.2.6`.
- `npm audit --json` now reports zero vulnerabilities for `scroll-down-web/web`.

Recommended fix: Keep the patch update and add a CI `npm audit --omit=dev` or equivalent production dependency gate.

#### F4. Public web could log production magic links when email provider was unset

Category: auth token handling, logging
Affected area: `scroll-down-web/web`
Severity: Medium
Confidence: High
Disposition: Fixed now

Why it matters: Magic-link URLs are bearer tokens. The previous development fallback logged the full sign-in link whenever `RESEND_API_KEY` was missing, regardless of `NODE_ENV`. If production email config drifted, live auth tokens would be written to logs.

Realistic exploit scenario: Production deploy misses `RESEND_API_KEY`; a user requests a sign-in link; anyone with log access can consume the token within its validity window.

Evidence:

- Fixed state: `scroll-down-web/web/src/lib/magic-link.ts:235-243` now throws in production when `RESEND_API_KEY` is unset and logs only outside production.
- `scroll-down-web/web/src/app/api/auth/send-link/route.ts:60-65` still returns generic success to avoid enumeration.

Recommended fix: Keep production fail-closed behavior and alert on delivery failures instead of logging tokens.

### Risky patterns and hardening opportunities

#### F5. Public web BFF exposes public endpoints backed by SDA admin sports routes

Category: API boundary, abuse, least privilege
Affected area: `scroll-down-web/web`, SDA sports API
Severity: Medium
Confidence: High
Disposition: Fix next

Why it matters: Public web routes proxy anonymous traffic to `/api/admin/sports/games` and `/api/admin/sports/games/{id}` with a server-side key. This is better than exposing the key to the browser, but it couples the public product to an admin API contract and relies on backend validation/rate limiting to bound anonymous query fan-out.

Realistic exploit scenario: A bot generates high-cardinality query strings and game IDs through `/api/games` and `/api/games/{id}`, creating cache churn and upstream load under the public web's privileged API key.

Evidence:

- `scroll-down-web/web/src/app/api/games/route.ts:7-15` forwards raw query parameters to `/api/admin/sports/games`.
- `scroll-down-web/web/src/app/api/games/[id]/route.ts:10-16` forwards the path parameter directly to `/api/admin/sports/games/{id}`.
- `scroll-down-web/web/src/lib/api-server.ts:127-143` injects `X-API-Key`.

Recommended fix: Move public web to consumer `/api/v1` endpoints with read-only key scope. Add BFF-side schema validation for dates, league, limit, IDs, and channel names before forwarding.

#### F6. SDA `/metrics` is unauthenticated if the API service is internet reachable

Category: operational exposure
Affected area: SDA FastAPI deployment
Severity: Medium
Confidence: Medium
Disposition: Verify deployment or protect

Why it matters: Prometheus metrics can expose operational paths, error rates, route names, and capacity signals. The code exposes `/metrics` without an API key.

Realistic exploit scenario: If `sda.dock108.dev/metrics` is public, attackers can observe deployment shape and identify high-value or unstable endpoints.

Evidence:

- `sports-data-admin/api/main.py:260-263` returns Prometheus metrics without auth.
- No code-level allowlist or auth guard is attached to this route.

Recommended fix: Restrict `/metrics` at the reverse proxy/network layer or require a metrics-specific token. Keep `/health` minimal for public uptime checks.

#### F7. Backend reset-token JWTs are replayable if auth router is mounted

Category: authentication recovery
Affected area: SDA auth router
Severity: Medium
Confidence: Medium
Disposition: Investigate before mounting auth

Why it matters: The auth router is not mounted in the current `main.py`, but if it is enabled, reset tokens are stateless JWTs valid until expiration. After a successful password reset, the same token can be reused during the remaining lifetime unless additional invalidation exists elsewhere.

Evidence:

- `sports-data-admin/api/app/dependencies/roles.py:76-101` creates and decodes reset JWTs without one-time state.
- `sports-data-admin/api/main.py` currently does not include `auth.router`, so this is dormant in the active app.

Recommended fix: Before mounting auth, store reset token hashes with `used_at`, or include a password-version/password-changed timestamp claim and reject stale tokens.

#### F8. Deprecated commerce/Stripe code remains in the repo

Category: dead surface, removal
Affected area: SDA commerce router
Severity: Low
Confidence: High
Disposition: Deprecated; remove rather than harden

Why it matters: Commerce, billing, and Stripe are out of scope for this product hardening pass and should not become part of the production attack surface by accident. The commerce router is not mounted by the active `main.py`; remaining references should be treated as deprecated code scheduled for removal.

Evidence:

- `sports-data-admin/api/app/routers/commerce.py` remains in the tree but is not mounted by active `main.py`.
- `sports-data-admin/api/main.py` currently does not include `commerce.router`.

Recommended fix: Remove commerce/billing/Stripe routes, tests, dependencies, config, and UI entry points in a dedicated cleanup. Until then, keep them unmounted and mark them as deprecated.

#### F9. Structured logging redacts field names but not arbitrary exception strings

Category: logging and privacy
Affected area: SDA backend logging
Severity: Low
Confidence: Medium
Disposition: Harden later

Why it matters: The structured formatter redacts known extra field names, but values in generic fields such as `error` or exception strings can still contain provider responses, URLs, emails, or tokens.

Evidence:

- `sports-data-admin/api/app/logging_config.py:13-24` redacts by exact extra field names.
- Several third-party error paths log `extra={"error": str(exc)}`; deprecated commerce/Stripe paths should be removed rather than hardened.

Recommended fix: Add a recursive redaction helper for log values, redact sensitive substrings, and avoid logging full third-party response bodies except in tightly controlled debug channels.

### Intentional or acceptable patterns worth documenting

- SDA production config validation is strong for key basics: production/staging requires explicit CORS origins, strong `API_KEY`, changed/long `JWT_SECRET`, and `AUTH_ENABLED=true` (`sports-data-admin/api/app/config.py:196-219`).
- SDA disables FastAPI docs/OpenAPI in production/staging (`sports-data-admin/api/main.py:61-69`).
- SDA and both Next.js apps set meaningful baseline browser security headers (`sports-data-admin/api/app/middleware/security_headers.py`, `sports-data-admin/web/next.config.ts`, `scroll-down-web/web/next.config.ts`).
- External links with `target="_blank"` in public web already use `rel="noopener noreferrer"`.
- iOS DEBUG-only fixture shortcuts are compile-gated and not present in Release behavior.
- iOS `UserDefaults` persistence stores local sports state, not credentials. The API key comes from app configuration, not local persisted state.
- Public web's broader CSP is consistent with ads/affiliate/Plausible integrations, but it should be monitored because it intentionally allows more third-party browser code. Stripe CSP entries were removed as part of billing deprecation.

### Unclear items needing manual verification outside the repo

- Confirm whether SDA `/metrics`, `/ready`, and `/healthz` are internet reachable or edge-restricted.
- Confirm whether the iOS release build is currently shipping an admin `SDA_API_KEY`; a private ignored `Config/Local.xcconfig` exists in this workspace and should be treated as sensitive local material.
- Confirm whether dormant SDA auth, onboarding, billing, webhook, golf, odds, and analytics routers are intentionally disabled for production or mounted through another entrypoint not reviewed here. Commerce/billing/Stripe code is deprecated and should be removed.
- Confirm Redis-backed rate limiting is enabled in production for shared-instance auth/onboarding/SSE limits.
- Confirm deployment secret scanning covers ignored local files before packaging or screenshots/log attachments.

## D. Safe hardening changes implemented

- Protected every SDA admin web `/proxy/*` request with the existing admin Basic auth gate, instead of only selected proxy prefixes.
- Stripped upstream `Location` headers from the SDA admin credential-injecting proxy to avoid leaking internal backend hostnames through redirects.
- Changed public web magic-link delivery to fail closed in production when `RESEND_API_KEY` is missing, while preserving the dev console-link fallback.
- Added a unit test that production magic links are not logged when email configuration is missing.
- Upgraded public web `next` from `16.2.4` to `16.2.6`.
- Ran `npm audit fix` for the public web dev-only `brace-expansion` advisory in the ESLint chain.

## E. Repo-specific remediation roadmap

| Priority | Summary | Why it matters | Approach | Complexity | Change risk | Owner |
|---:|---|---|---|---|---|---|
| P0 | Move iOS off `/api/admin` and off admin `API_KEY` | Mobile secrets are extractable | Add consumer/mobile SDA endpoints, return minimum game list/detail fields, require `CONSUMER_API_KEY`, update iOS client paths/config | Medium | Medium | Backend + iOS |
| P0 | Keep all admin web `/proxy/*` behind auth | Proxy injects admin key | Preserve implemented middleware change and regression test | Small | Low | Frontend/platform |
| P0 | Keep public web Next at fixed patch level | Verified high advisories existed | Preserve `next 16.2.6`; add CI audit gate | Small | Low | Frontend |
| P1 | Add public-web BFF input schemas | Reduces abuse/load and accidental admin API coupling | Validate `limit`, date ranges, league, IDs, channels; reject unknown query params | Small | Low | Frontend/backend |
| P1 | Protect or edge-restrict `/metrics` | Avoids operational intel exposure | Require token or reverse-proxy allowlist; keep liveness minimal | Small | Low | DevOps/platform |
| P1 | Add consumer API parity for public web | Removes need to proxy admin sports routes | Add `/api/v1/games` list/detail endpoints with read-only scope and public-safe fields | Medium | Medium | Backend |
| P2 | Harden dormant auth before mounting | Reset-token replay and localStorage JWT patterns | One-time reset tokens; HttpOnly cookie sessions; explicit mount decision | Medium | Medium | Backend/frontend |
| P2 | Remove deprecated commerce/billing/Stripe code | Avoids dormant payment surface becoming production attack surface | Delete routes, UI entry points, config, tests, dependencies, and CSP entries after product sign-off | Medium | Medium | Backend/frontend/product |
| P2 | Improve log redaction | Prevents accidental third-party/token leakage | Recursive redaction for error values and provider response bodies | Medium | Low | Backend/platform |
| P3 | Formalize secret handling for iOS builds | Avoids shipping/admin key confusion | CI build-time checks: no admin key in release, key scope labels, rotation runbook | Medium | Medium | Platform/iOS/security |
| P3 | Tighten public CSP over time | Reduces browser third-party risk | Inventory ads/affiliate scripts, split routes if possible, use nonces where practical | Large | Medium | Frontend/product |

## F. Security testing recommendations

- Add an SDA admin web test asserting unauthenticated `/proxy/api/v1/*`, `/proxy/metrics`, `/proxy/healthz`, and future `/proxy/*` paths return 401 in production.
- Add public-web BFF unit tests for rejected invalid game IDs, excessive `limit`, invalid dates, unsupported leagues, and overlong query strings.
- Add backend authz tests proving `CONSUMER_API_KEY` cannot access `/api/admin/*` and admin `API_KEY` is rejected on consumer routes when keys differ.
- Add iOS integration tests against consumer endpoints once they exist; include a build check that Release does not use `/api/admin` paths.
- Add route inventory tests for SDA that fail when new routers are mounted outside `/api/v1` or `/api/admin`, and require explicit auth class documentation.
- Add CI gates: `npm audit --omit=dev` for both Next apps, full `npm audit` as warning or scheduled job, `pip-audit` for API/scraper lockfiles, and secret scanning.
- Add header verification tests for the public web, admin web, and SDA API.
- Add log assertions for sensitive auth and email flows: no magic tokens, reset tokens, API keys, Authorization headers, or full provider response bodies.
- Add abuse tests for magic-link send limits, SSE channel caps, public game listing cardinality, and AI story rate limits.

## G. Leadership summary

The biggest actual risk is privilege boundary drift: the iOS app and public web are currently consuming admin-scoped SDA sports APIs, and the mobile app model can expose a static API key. The SDA admin web proxy also had a real credential-injection boundary flaw, but that was fixed in this review.

The codebase already has several good controls: production config validation, docs disabled in production, API key scoping primitives, security headers, structured request logging, rate-limit middleware, generic backend 500s, and ignored iOS local secrets.

Before broader mobile exposure, move iOS to read-only consumer endpoints and stop embedding any admin-scoped key. For the public web, validate BFF inputs and migrate the anonymous traffic path to consumer APIs. Operationally, confirm `/metrics` is not publicly reachable and keep dependency/security audit gates in CI.

Lower-priority hardening can be phased in: improve log redaction, remove deprecated commerce/billing/Stripe routes, harden dormant auth before mounting it, and gradually reduce public-web third-party browser script exposure where product constraints allow.
