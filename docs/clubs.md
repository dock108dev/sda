# Club Provisioning

Self-serve club provisioning allows golf pool operators to sign up, pay, and get a working club without manual intervention.

## Overview

A **club** is a multi-tenant unit: one club owns multiple golf pools, one or more admin users, and one Stripe subscription. Clubs are identified by a unique URL slug (e.g., `/clubs/rvcc`).

The provisioning flow:

```
1. Prospect submits "claim your club" form  →  club_claims record created
2. Operator initiates checkout               →  Stripe checkout session + onboarding_session created
3. Customer pays                             →  Stripe sends checkout.session.completed webhook
4. Webhook advances session to "paid"        →  claim_token issued
5. Customer clicks claim link                →  account created, club provisioned, session → "claimed"
```

---

## Database Tables

See [Database](database.md#club-provisioning--commerce) for full schema details.

| Table | Role |
|-------|------|
| `club_claims` | Form submissions awaiting checkout |
| `clubs` | Provisioned tenant records |
| `club_memberships` | Club-scoped RBAC (owner/admin) |
| `onboarding_sessions` | Session state tracking |
| `magic_link_tokens` | Passwordless auth tokens |
| `stripe_customers` | Stripe customer linkage |
| `stripe_subscriptions` | Subscription state |
| `processed_stripe_events` | Idempotency dedup |
| `pool_lifecycle_events` | Pool state machine audit |
| `audit_events` | Provisioning/payment audit log |
| `webhook_delivery_attempts` | Webhook retry tracking |

---

## API Endpoints

### Onboarding (no auth)

```
POST /api/onboarding/club-claims
```
Submit a "claim your club" interest form. Triggers a notification email to the operator. Returns `claim_id` used to initiate checkout.

Request:
```json
{
  "clubName": "River Valley CC",
  "contactEmail": "admin@rvcc.org",
  "expectedEntries": 150,
  "notes": "Masters pool, 150 members"
}
```

Response:
```json
{ "claimId": "abc123", "receivedAt": "2026-04-21T12:00:00Z" }
```

---

```
GET /api/onboarding/session/{token}
```
Poll onboarding session status. Used by the frontend to detect when payment completes.

Response:
```json
{ "status": "paid", "claimToken": "xyz..." }
```

States: `pending → paid → claimed → expired`

---

```
POST /api/onboarding/claim
```
Exchange a `claim_token` for a provisioned account. Creates the user account and club if they don't exist. Advances session to `claimed`.

Request:
```json
{ "claimToken": "xyz...", "password": "optional" }
```

---

### Commerce (API key required)

```
POST /api/v1/commerce/checkout
```
Create a Stripe checkout session for a given plan and claim.

Request:
```json
{ "planId": "price_starter", "clubClaimId": "abc123" }
```

Response:
```json
{ "checkoutUrl": "https://checkout.stripe.com/...", "sessionToken": "..." }
```

Available plan IDs: `price_starter` ($29/mo), `price_pro` ($99/mo), `price_enterprise` ($299/mo)

---

### Webhooks (Stripe-signed, no other auth)

```
POST /api/webhooks/stripe
```
Handles Stripe events. Signature verified via `Stripe-Signature` header and `STRIPE_WEBHOOK_SECRET`. Idempotent via `processed_stripe_events` table.

Handled events:
- `checkout.session.completed` — advances `onboarding_sessions` status to `paid`
- `customer.subscription.updated` — syncs `stripe_subscriptions` record
- `customer.subscription.deleted` — marks subscription cancelled; suspends club if applicable
- `invoice.payment_failed` — sends dunning email

---

### Clubs (no auth)

```
GET /api/v1/clubs/{slug}
```
Returns club info and its active pools (status: `open`, `locked`, or `live`). Returns 404 for unknown or suspended/cancelled clubs. Used by public entry pages at `/clubs/{slug}/`.

Response:
```json
{
  "clubId": "...",
  "slug": "rvcc",
  "name": "River Valley CC",
  "pools": [
    {
      "poolId": 1,
      "name": "Masters 2026",
      "status": "open",
      "tournamentId": 42,
      "entryDeadline": "2026-04-10T12:00:00Z",
      "allowSelfServiceEntry": true
    }
  ]
}
```

---

### Billing (JWT required, club owner only)

```
POST /api/v1/billing/portal
```
Create a Stripe Customer Portal session for self-service subscription management (cancel, update payment method, view invoices). Caller must be the `owner` of the specified club.

Request:
```json
{ "clubId": "abc-uuid" }
```

Response:
```json
{ "url": "https://billing.stripe.com/..." }
```

---

### Club Branding (JWT required, owner + premium plan)

```
PUT /api/v1/clubs/{id}/branding
```
Update a club's `branding_json` (logo URL, colors, etc.). Gated by plan entitlement.

---

### Club Memberships (JWT required)

Club RBAC is managed via `club_memberships`. Roles:
- `owner` — set during provisioning, full access
- `admin` — invited by owner, can manage pools and entries

Invite flow: owner invites user by email → invite record created → invited user accepts → `accepted_at` populated.

---

## Entitlements

`EntitlementService` (`api/app/services/entitlement.py`) enforces plan limits. It is called at the point of action, not at auth time.

| Error | HTTP | Meaning |
|-------|------|---------|
| `EntitlementError` | 403 | Feature not available on current plan |
| `SeatLimitError` | 402 | Club has reached its admin seat limit |
| `SubscriptionPastDueError` | 402 | Subscription payment is overdue |
| `TransitionError` | 409 | Pool state machine transition is not allowed |

Global exception handlers in `api/main.py` convert these to structured JSON responses.

---

## Pool Lifecycle

Pool status transitions are guarded by the state machine in `api/app/services/pool_lifecycle.py`. Every transition is recorded in `pool_lifecycle_events`.

```
draft → open → locked → live → completed
```

- `draft` — created during provisioning, no tournament linked yet
- `open` — accepting entries (requires tournament link and entry deadline)
- `locked` — entry deadline passed, no new entries
- `live` — tournament in progress, live scoring active
- `completed` — tournament complete, final scores posted

---

## Configuration

| Setting | Purpose |
|---------|---------|
| `STRIPE_SECRET_KEY` | Stripe API key for checkout and portal |
| `STRIPE_WEBHOOK_SECRET` | Webhook signature verification secret |
| `STRIPE_CHECKOUT_SUCCESS_URL` | Redirect URL after successful checkout |
| `STRIPE_CHECKOUT_CANCEL_URL` | Redirect URL on checkout cancellation |
| `ONBOARDING_NOTIFICATION_EMAIL` | Email address for new claim notifications (optional) |

---

## Idempotency

Three layers prevent double-processing:

1. **HTTP idempotency keys** — checkout session creation is idempotent within a claim
2. **`processed_stripe_events`** — `ON CONFLICT DO NOTHING` prevents duplicate webhook handling
3. **`onboarding_sessions` state machine** — transitions are guarded; re-processing a `paid` event on an already-`paid` session is a no-op

---

## Audit Log

Every provisioning, payment, and lifecycle event writes to `audit_events`. Query by:
- `event_type` — e.g., `club.provisioned`, `payment.confirmed`, `pool.transitioned`
- `club_id` — all events for a club
- `created_at` — time range

Admin access via `GET /api/admin/audit` (admin role required).
