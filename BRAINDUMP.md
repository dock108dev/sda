# BRAINDUMP — Backend / API

## Goal

Replace the manual claim-my-club workflow with a backend that can actually provision a club end-to-end after payment.

The system should support:
- online checkout
- immediate customer/account provisioning
- club creation
- admin access assignment
- pool configuration
- draft/open/published state management
- public entry collection
- subscription-aware limits

The frontend can only feel self-serve if the backend really is self-serve.

Right now the manual form is basically hiding missing system behavior. This backend pass is about making the product real.

---

## Core backend outcome

After a successful payment, the backend should be able to support this full lifecycle without me doing anything manually:

1. Customer purchases plan
2. System records payment and entitlements
3. Club onboarding session is created
4. User creates or activates admin account
5. Club record is created
6. Club-specific admin access is granted
7. First pool is created in draft
8. Pool config is validated and saved
9. Pool is published or scheduled
10. Public entry page becomes available
11. Entries are accepted
12. Leaderboard/export/admin management all work under that club

That is the actual product flow.

---

## Existing hidden problem

The current manual sign-on flow is doing operational work that the API should be doing.

The form is currently standing in for:
- lead intake
- payment intent without payment
- club creation request
- admin provisioning request
- informal pool requirements gathering
- support triage

That all needs to be replaced by explicit backend models and endpoints.

---

## Backend domains we need

There are several distinct domains here that should not be blurred together.

### 1. Billing / commerce
Handles:
- plans
- checkout
- subscriptions / one-time purchases
- payment status
- entitlement calculation
- receipts / provider references

### 2. Identity / auth
Handles:
- club admin account creation
- login
- account activation
- password / magic link workflows
- session handling

### 3. Clubs / tenancy
Handles:
- club record
- club slug / subdomain
- branding
- ownership
- club membership / roles
- club-scoped data isolation

### 4. Pool management
Handles:
- tournaments
- pool templates
- pool config schema
- draft/open/locked/final lifecycle
- duplication
- publication state

### 5. Entries
Handles:
- public entry submission
- entry validation
- participant data
- lock enforcement
- duplicate / edit rules
- CSV import/export

### 6. Reporting / leaderboard
Handles:
- standings
- scoring / ranking
- export
- maybe async leaderboard refresh depending on data model

The more these are cleanly separated now, the less pain later.

---

## Recommended backend architecture shape

This does not need to become some giant microservice mess. One app is fine. But the domains need strong boundaries.

Suggested modules:
- `billing`
- `auth`
- `clubs`
- `subscriptions`
- `tournaments`
- `pool_templates`
- `pools`
- `entries`
- `leaderboards`
- `admin`
- `public`

If using a monolith, keep the internal services crisp and the API routes separated by domain.

---

## Data model thinking

### Club
Core fields:
- `id`
- `name`
- `slug`
- `status` (`pending`, `active`, `suspended`, maybe `archived`)
- `contact_email`
- `timezone`
- `branding_config`
- `created_at`
- `updated_at`

### User
Core fields:
- `id`
- `email`
- `password_hash` or auth provider linkage
- `first_name`
- `last_name`
- `status`
- `created_at`
- `updated_at`

### ClubMembership
This is important. Do not hardcode a single user-owner forever.

Fields:
- `id`
- `club_id`
- `user_id`
- `role` (`owner`, `admin`, maybe `viewer` later)
- `status`

### ProductPlan
Fields:
- `id`
- `code` (`single_pool`, `annual_weekly`)
- `name`
- `billing_type` (`one_time`, `subscription`)
- `price`
- `currency`
- `feature_flags`
- `limits`

### Purchase / Subscription
Need a normalized commerce layer whether provider is Stripe or anything else.

Fields:
- `id`
- `user_email` or `customer_id`
- `plan_code`
- `provider`
- `provider_customer_id`
- `provider_checkout_session_id`
- `provider_subscription_id`
- `status`
- `purchased_at`
- `expires_at`
- `metadata`

### Entitlement
This is what the app should actually use for authorization and limits, not raw billing objects.

Fields:
- `id`
- `club_id` or pre-club onboarding token link
- `plan_code`
- `active`
- `max_active_pools`
- `supports_unlimited_entries`
- `supports_custom_branding`
- `period_start`
- `period_end`

### OnboardingSession
Important for bridging payment to actual setup.

Fields:
- `id`
- `purchase_id`
- `email`
- `status`
- `selected_plan`
- `club_id` nullable
- `user_id` nullable
- `bootstrap_payload`
- `expires_at`

This is how we recover safely if payment succeeds but setup is unfinished.

### Tournament
Fields:
- `id`
- `name`
- `tour`
- `season`
- `starts_at`
- `locks_at`
- `status`
- maybe source identifiers

### Pool
Fields:
- `id`
- `club_id`
- `tournament_id`
- `name`
- `slug`
- `format_type`
- `status` (`draft`, `open`, `locked`, `live`, `final`, `archived`)
- `config_json`
- `entry_open_at`
- `entry_lock_at`
- `published_at`
- `created_by_user_id`

### PoolTemplate
Potentially separate or derived from common configs:
- `id`
- `club_id` nullable for system templates
- `name`
- `format_type`
- `config_json`
- `is_system_template`

### Entry
Fields:
- `id`
- `pool_id`
- `participant_name`
- `participant_email`
- `entry_name`
- `picks_json`
- `status`
- `submitted_at`
- `locked_at`
- maybe payment linkage if entry fees ever come later

### PoolConfigVersion
This is worth considering early if config changes after launch matter.

Fields:
- `id`
- `pool_id`
- `version`
- `config_json`
- `created_at`
- `created_by_user_id`

That gives a history trail and helps avoid “what changed?” pain.

---

## Billing / checkout backend

### Need a real commerce pipeline
The backend needs endpoints and webhook handling for:
- create checkout session
- checkout success resolution
- webhook verification
- purchase persistence
- entitlement creation / activation
- recoverable onboarding token creation

### Strong recommendation
Use webhook as source of truth for payment completion, not only redirect success.

Frontend redirect is for UX.
Webhook is for system truth.

### Commerce flow
1. Client requests checkout for plan
2. Backend creates provider checkout session
3. Provider redirects back on success
4. Webhook marks purchase paid
5. Backend creates onboarding session
6. Frontend loads onboarding using secure token/session
7. Provisioning finishes after onboarding submit

### Must handle
- redirect success arrives before webhook
- webhook retries
- duplicate events
- checkout canceled
- expired sessions
- one-time purchase vs subscription differences
- annual renewal / expiration logic

---

## Auth / account creation

Do not bury auth inside checkout logic.

### Recommended approach
- payment can happen before full account creation if needed
- onboarding session ties purchase to email
- after payment, user creates account or claims account tied to that email
- backend attaches purchase + onboarding + club to that user

### Why
This keeps commerce and auth coupled but not entangled.

### Must handle
- user email already exists
- different email used for account creation than checkout
- invite future club admins later
- magic link or password reset post-purchase
- onboarding resume after auth expires

---

## Club provisioning

This is the real new backend capability.

A club provisioning service should:
- validate entitlement
- create club
- reserve slug
- attach owner membership
- initialize default settings
- optionally create default template(s)
- create initial pool if included in onboarding
- return dashboard bootstrap state

### Important rule
Provisioning should be idempotent.

If the request is retried because of timeout or frontend weirdness, it should not create:
- duplicate clubs
- duplicate pool records
- duplicate entitlements
- duplicate memberships

Use:
- idempotency keys
- onboarding session status
- transaction boundaries

---

## Pool configuration model

This is where backend can get ugly fast if the schema is fuzzy.

### Strong recommendation
Have a normalized `format_type` plus validated `config_json`.

Example:
- `format_type = straight_pick`
- `format_type = bucketed_pick`
- `format_type = weekly_tour`

Then validate config against a schema per type.

### Why
You want:
- flexibility
- API stability
- clear validation rules
- future room for new formats

### Example config structures

#### Straight pick
```json
{
  "total_picks": 7,
  "counting_picks": 5,
  "allow_edit_until_lock": false,
  "tiebreaker_type": "score_total"
}
```

#### Bucketed pick
```json
{
  "bucket_count": 6,
  "picks_per_bucket": 1,
  "counting_picks": 4,
  "bucket_source": "system_generated",
  "allow_manual_bucket_override": false
}
```

But the actual point is not these exact fields. The point is: each format needs explicit schema validation.

### Validation service
Need a pool config validator that checks:
- required fields per format
- numeric sanity
- cross-field relationships
- tournament timing compatibility
- entitlement constraints if any

---

## Pool lifecycle and state machine

This cannot just be random booleans.

### Suggested states
- `draft`
- `published`
- `open`
- `locked`
- `live`
- `final`
- `archived`

Depending on product semantics maybe `published` and `open` can be combined, but define it intentionally.

### Why state discipline matters
Admin flows will need clean rules:
- draft can be edited freely
- open accepts entries
- locked rejects new entries
- live shows active leaderboard
- final freezes results
- archived hidden by default

### State transitions should be explicit
Examples:
- `draft -> open`
- `draft -> published`
- `open -> locked`
- `locked -> live`
- `live -> final`
- `final -> archived`

No hidden magic.

---

## Public entry APIs

These routes are going to get used heavily, so keep them clean and stable.

### Read endpoints
- get club public info
- get pool public info
- get entry form metadata
- get player list / bucket list for selected tournament
- get rules summary

### Write endpoints
- submit entry
- maybe update entry before lock if supported
- maybe validate entry before final submit

### Validation rules
- pool must be open
- current time before lock
- picks must match config
- selected golfers must be valid for tournament
- bucket rules must be honored
- duplicate selections blocked where needed
- participant identity rules enforced

### Response quality matters
The public entry API should return structured validation errors the UI can map directly to fields.

---

## Admin APIs

Need club-scoped admin routes that are not mixed with public routes.

### Examples
- get dashboard summary
- list pools for club
- create draft pool
- update pool config
- publish pool
- open entries
- close entries
- duplicate pool
- list entries
- export entries
- manage branding
- manage club settings
- get billing / entitlement summary

### Important
Every admin endpoint should enforce:
- authenticated user
- club membership
- correct role
- entitlement / plan constraints where relevant

---

## Entitlements and plan enforcement

Do not litter this logic everywhere. Centralize it.

### Examples of rules
Single pool plan:
- one active pool at a time or one purchased pool total depending on business rule
- maybe no advanced branding
- maybe limited support tier

Annual plan:
- multiple pools allowed
- custom branding enabled
- ongoing tournament support
- maybe priority support marker

### Backend needs an entitlement service
So routes can ask:
- can this club create another pool?
- can this club use branding?
- is subscription active?
- is this purchase consumed?
- what plan does this club have?

This is much cleaner than checking plan code in ten different controllers.

---

## Tournament and player data dependencies

Pool setup depends on tournament data being ready and trustworthy.

Backend needs to expose:
- tournament catalog
- active/upcoming tournaments
- player lists for each tournament
- bucket generation source if system-generated buckets exist
- lock times derived from tournament schedule

### Important
The admin pool setup API should not force the frontend to guess tournament timing logic.

The backend should own:
- valid tournament choices
- official lock timestamps
- maybe timezone-normalized schedule data

---

## Provisioning sequence recommendation

### Flow A: strict post-payment onboarding
1. checkout complete
2. purchase marked paid
3. onboarding session created
4. user creates/claims account
5. user creates club
6. user creates first pool
7. club activated

### Flow B: account first then club/pool
If account creation must happen immediately after success page:
1. checkout complete
2. onboarding session loaded
3. account created
4. club + pool setup submitted in one provisioning call

Either is fine, but the backend should still use a durable onboarding session object.

---

## Webhooks / async processing

Need a clean job / event story.

### Commerce events
- checkout completed
- payment failed
- subscription renewed
- subscription canceled
- charge refunded

### Product events
- club provisioned
- pool published
- pool opened
- entry submitted
- pool locked

### Why this matters
You will eventually want:
- emails
- audit history
- admin notifications
- retries
- analytics
- maybe CRM sync later

Even if the first version is simple, structure events in a way that does not paint you into a corner.

---

## Email / notification opportunities

Not mandatory for day one, but the backend should at least leave room for:
- purchase confirmation
- onboarding incomplete reminder
- pool published confirmation
- entry confirmation
- lock reminder
- admin receipt / invoice message

Would not overbuild, but the event hooks should exist.

---

## Security and tenancy

This becomes a multi-tenant product the second clubs have their own admin access.

### Hard rules
- every admin resource is club-scoped
- every write action checks membership and role
- slugs are unique
- public routes expose only what should be public
- no trusting frontend plan limits
- no trusting frontend lock enforcement
- onboarding tokens expire
- payment state is verified server-side

### Nice to have early
- audit log for admin actions
- request id / trace id for operational debugging
- rate limiting on public entry submission
- anti-spam / abuse strategy for open public forms

---

## Idempotency and operational safety

This whole self-serve flow will create nasty bugs if retries are not handled intentionally.

### Areas requiring idempotency
- checkout session creation if retried by UI
- webhook handling
- onboarding completion submit
- club provisioning
- pool creation from onboarding
- entry submission if client double-posts

### Suggested mechanisms
- idempotency keys
- unique provider event ids
- unique purchase constraints
- onboarding session status transitions
- database transaction boundaries
- safe retry semantics

---

## Reporting and exports

The backend should treat export as a product feature, not a manual afterthought.

### Minimum export support
- entries CSV by pool
- maybe leaderboard CSV
- maybe roster/pick export depending on format

### API considerations
- synchronous export for small pools is fine
- if pools get large, move to async file generation
- keep export schema stable once clubs start relying on it

---

## Recommended API surface

### Public
- `GET /api/public/clubs/:slug`
- `GET /api/public/clubs/:slug/pools/:poolSlug`
- `GET /api/public/clubs/:slug/pools/:poolSlug/form`
- `POST /api/public/clubs/:slug/pools/:poolSlug/entries`

### Commerce
- `POST /api/commerce/checkout-sessions`
- `POST /api/commerce/webhooks/provider`
- `GET /api/commerce/onboarding-session`
- `POST /api/commerce/onboarding/complete`

### Auth
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/magic-link`
- `POST /api/auth/password/reset`

### Club admin
- `GET /api/club/me`
- `GET /api/club/current`
- `PATCH /api/club/current`
- `GET /api/club/current/billing`
- `GET /api/club/current/pools`
- `POST /api/club/current/pools`
- `PATCH /api/club/current/pools/:poolId`
- `POST /api/club/current/pools/:poolId/publish`
- `POST /api/club/current/pools/:poolId/open`
- `POST /api/club/current/pools/:poolId/close`
- `POST /api/club/current/pools/:poolId/duplicate`
- `GET /api/club/current/pools/:poolId/entries`
- `GET /api/club/current/pools/:poolId/export`

### Metadata
- `GET /api/metadata/plans`
- `GET /api/metadata/tournaments`
- `GET /api/metadata/pool-formats`
- `GET /api/metadata/tournaments/:id/players`

---

## Schema and validation strategy

### Use explicit server-side schemas
Need request validation for:
- checkout creation
- account creation
- club creation
- pool config submission
- entry submission

### Pool configs especially
Do not accept freeform JSON without format-aware validation.

Use schema versioning if possible:
- `format_type`
- `config_version`
- `config_json`

That gives future migration room.

---

## Operational/admin tooling needs

Even with self-serve, I still need minimal operator visibility.

### Internal/admin capabilities
- search purchases
- search clubs
- see onboarding sessions
- see failed provisioning attempts
- manually resend onboarding email maybe
- see entitlement state
- override / fix edge cases carefully
- inspect webhook failures

This can be minimal, but some operator surface is needed unless debugging is going to be hell.

---

## Migration / rollout strategy

Do not hard-switch from manual to self-serve without a staged plan.

### Suggested rollout
#### Phase 1
- keep pricing page
- build checkout backend
- build onboarding session model
- provision club + one pool
- support only the two main plans
- support only the primary pool formats

#### Phase 2
- enable full club admin dashboard flows
- add duplication / templates
- add annual multi-pool lifecycle
- improve exports
- add notifications

#### Phase 3
- advanced branding
- multiple admins
- richer analytics
- more complex format controls
- maybe club invite flows

### Important
Manual fallback can remain for edge cases, but it should be clearly outside the happy path.

---

## Acceptance criteria for backend

### Commerce
- successful payment produces durable purchase record
- payment completion is confirmed server-side
- onboarding session is created and recoverable

### Provisioning
- club can be created from paid onboarding
- admin account can be attached correctly
- first pool can be created during onboarding
- provisioning is idempotent

### Pools
- format-specific config is validated server-side
- pool lifecycle state rules are enforced
- plan entitlements are enforced centrally

### Public entry
- entry submission respects pool config and lock rules
- invalid submissions return structured errors
- club public pages only expose intended data

### Security
- club data is tenant-safe
- admin routes require membership and role checks
- public write endpoints have abuse controls

### Operability
- failed webhooks can be retried safely
- failed onboarding can be resumed
- support can inspect purchase/onboarding/club linkage when something goes weird

---

## Open backend questions

These need decisions but not hand-wringing.

- Is a single-pool purchase consumed forever after first launch, or can it remain attached to one pool lifecycle until archived?
- Does annual plan allow unlimited simultaneous active pools or just unlimited across the year?
- Are club URLs subdomain-based from day one or path-based first?
- Will public entries ever be paid individually, or is club payment the only commerce layer?
- Do we want magic-link auth, password auth, or hybrid?
- Should pool duplication clone everything including schedule and bucket config?
- What exact leaderboard/scoring engine already exists and how much of it is reusable here?
- What tournament/player data APIs already exist and are stable enough for this flow?

---

## My bias / recommendation

Backend should prioritize these principles:
- durable purchase truth
- explicit onboarding session
- idempotent provisioning
- club-scoped tenancy
- schema-validated pool configs
- centralized entitlement enforcement
- clean public vs admin API separation

Main thing:
the manual sign-on form should become an exception path for weird customers, not the core product path.

The backend should make “pay, get account, set up club, launch pool” feel like the normal and reliable way the system works.
