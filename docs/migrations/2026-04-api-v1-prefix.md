# API v1 Prefix Migration — 2026-04

**Status:** Shipped 2026-04-22. No grace period; old paths return 404.

## What changed

Consumer endpoints introduced during the club-provisioning work landed under
`/api/clubs/*`, `/api/billing/*`, and `/api/commerce/*` in pre-release builds.
Per the project convention (`CLAUDE.md`: "Consumer endpoints go under
`/api/v1/`. Admin under `/api/admin/`. Don't mix."), these routes have been
moved to the `/api/v1/` namespace. The lint at
`scripts/lint_router_namespaces.py` enforces this going forward.

## Old → New

| Method   | Old path                                         | New path                                            |
| -------- | ------------------------------------------------ | --------------------------------------------------- |
| `GET`    | `/api/clubs/{slug}`                              | `/api/v1/clubs/{slug}`                              |
| `PUT`    | `/api/clubs/{club_id}/branding`                  | `/api/v1/clubs/{club_id}/branding`                  |
| `POST`   | `/api/clubs/invites/{token}/accept`              | `/api/v1/clubs/invites/{token}/accept`              |
| `POST`   | `/api/clubs/{club_id}/invites`                   | `/api/v1/clubs/{club_id}/invites`                   |
| `GET`    | `/api/clubs/{club_id}/members`                   | `/api/v1/clubs/{club_id}/members`                   |
| `DELETE` | `/api/clubs/{club_id}/members/{target_user_id}`  | `/api/v1/clubs/{club_id}/members/{target_user_id}`  |
| `POST`   | `/api/billing/portal`                            | `/api/v1/billing/portal`                            |
| `POST`   | `/api/commerce/checkout`                         | `/api/v1/commerce/checkout`                         |

Request bodies, response shapes, authentication, and status codes are
unchanged. Only the URL prefix moves.

## What is *not* changing

These endpoints stay at their current (unversioned) paths and are explicitly
exempted from the namespace lint:

- `/health`, `/ready`, `/metrics` — Kubernetes probes and Prometheus scrape.
- `/api/webhooks/stripe` — URL is configured in the Stripe dashboard; Stripe
  owns the callback target.
- `/api/onboarding/club-claims`, `/api/onboarding/claim`,
  `/api/onboarding/session/{session_token}` — public, pre-signup onboarding
  flow. Not a consumer (authenticated) or admin surface; rate-limited per-IP.

Do **not** rewrite callers of the paths above — they are correct as-is.

## Who is affected

Anything that calls the clubs/billing/commerce paths directly:

- The SPA in `web/` (updated in the same change — see
  `web/src/lib/api/clubs.ts`).
- Any external integrator, curl script, Postman collection, or internal
  tool that hit the pre-release paths.

## Rollout

No dual-mount. Per `CLAUDE.md`'s "Don't add backwards-compat shims" rule,
the old routes are removed in the same change. Out-of-repo consumers must
update before their next request.

## How to verify you caught every caller

Run this grep across your repo:

```sh
grep -rnE '/api/(clubs|billing|commerce)(/|"|'"'"'|\b)' \
     --exclude-dir=node_modules --exclude-dir=.git .
```

Any hit that is **not** under `/api/v1/` needs updating. Then smoke-test one
authenticated call and one public call:

```sh
# Public club lookup — should 200 (or 404 for unknown slug)
curl -i https://$HOST/api/v1/clubs/some-slug

# Pre-migration path — should now 404
curl -i https://$HOST/api/clubs/some-slug
```

## Related

- Project convention: `CLAUDE.md` → "API" section
- Enforcement lint: `scripts/lint_router_namespaces.py`
- Changelog entry: `docs/changelog.md` (2026-04-22)
