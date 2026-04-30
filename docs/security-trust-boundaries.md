# Security trust boundaries (API)

## Edge headers and admin origin resolution

`app.dependencies.roles._is_admin_origin` grants an implicit **admin** role when
the request has no JWT but `Origin`, `Referer`, or (optionally)
`X-Forwarded-Origin` matches `ADMIN_ORIGINS`.

- **`X-Forwarded-Origin`** is ignored unless `TRUST_FORWARDED_ORIGIN=true` in
  the API environment. Enable it **only** when your load balancer or ingress
  **strips** this header from untrusted clients and your trusted proxy sets it
  for internal admin traffic.
- Prefer **`Origin`** from real browser calls to the API over forwarded
  headers.

## API keys and JWT on the same request

When `X-API-Key` passes `verify_api_key`, `resolve_role` treats the caller as
admin **unless** a Bearer JWT is also present — then the **JWT role wins**. This
prevents a non-admin user from gaining admin privileges solely because a
reverse proxy injected the admin API key.

## Realtime (SSE / WebSocket)

- **SSE**: Prefer `X-API-Key`; `api_key` query exists for browser `EventSource`
  limitations. Avoid logging full request URLs that contain query keys.
- **WebSocket**: `Origin` is validated when present; integrations without
  `Origin` still require a valid API key.

## Rate limiting

- **`RATE_LIMIT_USE_REDIS`**: When `true`, auth-strict and onboarding-strict
  tiers use Redis fixed-window counters (shared across replicas). Failures
  fall back to in-memory limits.
- **`/v1/sse`**: Uses a dedicated bucket (same numeric defaults as keyed REST
  traffic), not an unlimited bypass.

## Dependency scanning

The workflow job **Security · pip-audit + pnpm audit (advisory)** runs
`pip-audit` on `api/requirements.txt` and `pnpm audit` at the repo root. It is
`continue-on-error: true` so dependency noise does not block merges; treat
findings as inputs to upgrade planning.
