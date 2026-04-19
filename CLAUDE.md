# Claude Instructions

Project: sports data + narrative pipeline. See `ARCHITECTURE.md`, `DESIGN.md`, `ROADMAP.md`, and `BRAINDUMP.md` for full context. Research docs in `docs/research/`.

## Before you change code

- Read the relevant section of `ARCHITECTURE.md` for the component you're touching.
- Check `ROADMAP.md` to see which phase the change belongs to — don't do Phase 4 work in a Phase 1 PR.
- Check `docs/research/` for the topic. 17 docs cover the hard decisions (golden corpus, grading, LISTEN/NOTIFY, Redis Streams, OTel, etc.). Cite them in PR descriptions.

## Project conventions (enforce these in every change)

### API
- camelCase response fields via Pydantic `Field(alias=...)`, never snake_case on the wire.
- Scores: `{home, away}` object (Phase 2 target). If you touch a tuple-returning endpoint, migrate it.
- Never add nullable `isLive`/`isFinal`/`isPregame` — compute them.
- Consumer endpoints go under `/api/v1/`. Admin under `/api/admin/`. Don't mix.
- Every new finite string field is an enum.

### DB
- SQLAlchemy 2.0 async, `Mapped[...]` annotations.
- Every FK declares `ondelete`.
- JSONB only for genuinely flexible blobs — if you query on it, it's a column.
- Enum changes: add-then-rename, not in-place drop. See `docs/research/alembic-enum-sync-strategies.md`.

### Celery
- Queue per concern (`sports-scraper`, `social-scraper`, `social-bulk`, `training`).
- Redis `SET NX` lock on every event-dispatched task.
- Task expiry always set.
- Prefer ORM hooks / `LISTEN/NOTIFY` over beat for event-shaped work.

### Pipeline
- Deterministic grouping, AI narration only. Don't let LLM output drive block structure.
- 3-layer prompt (identity + data + guardrails). Keep stable and volatile content in separate layers.
- Validation is non-negotiable. Fallback to templates is a first-class path, not a bug.
- Any prompt or validation change must pass the golden corpus (Phase 1).

### Realtime
- SSE for consumer, WebSocket for admin.
- Sequence numbers + boot epoch on every event.
- Patches for live updates, full refetch only on phase change.

### Frontend
- Keep `guardrails.ts` in sync with backend `validate_blocks.py`. If they diverge, align in the same PR.
- Types live in `packages/js-core/`. Mirror API changes there before consuming them in `web/`.

## What to avoid

- **Don't add sentiment analysis on official team tweets.** It's noise; see `BRAINDUMP.md`.
- **Don't add backwards-compat shims** for pre-Phase-2 contracts once migrated — cut cleanly.
- **Don't add per-endpoint score swaps.** Use the shared helper, or migrate to the object type.
- **Don't silently null contract fields.** Use explicit `UNKNOWN` enum values when you can't compute.
- **Don't introduce consumer logic into admin routers** or vice versa.
- **Don't add new daily-batch scheduling for anything event-shaped.** If it should happen on a game transition, dispatch on the transition.
- **Don't write moments-based consumer code.** Blocks are the consumer layer; moments are internal.
- **Don't expand Playwright-based social scraping surface area.** The direction is stabilize + reduce, not grow.

## Testing

- Pipeline changes: run the golden corpus (Phase 1 infra). No regressions, no merge.
- API changes: contract test against OpenAPI schema dump; frontend TS types must compile.
- DB changes: Alembic up + down must be clean on a seeded dev DB.
- Realtime changes: load test before merging anything that touches pub/sub or poller.

## Where things live

- Pipeline stages: `api/app/services/pipeline/stages/`
- Flow validation: `api/app/services/pipeline/stages/validate_blocks.py`
- Frontend guardrails: `web/src/lib/guardrails.ts`
- Odds EV + FairBet: `scraper/sports_scraper/odds/` + `api/app/services/`
- Realtime fanout: `api/app/realtime/`
- Shared TS types: `packages/js-core/`
- Migrations: `api/alembic/versions/`

## When unsure

- Check `BRAINDUMP.md` for the opinionated read on what's solid vs fragile vs legacy.
- Check the research doc for your topic before designing from scratch.
- If the change doesn't fit a current ROADMAP phase, ask before building — scope creep across phases is the main failure mode here.
