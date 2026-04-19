# Game Flow Version Semantics

Two independent version strings live on every `SportsGameFlow` row.

## `story_version`

Tracks the **overall pipeline schema** — the structure of `moments_json`, how plays are
grouped, and which pipeline stages produced the row. It is the primary discriminator used
by query filters to select the "current generation" of flows.

| Value | Status | Description |
|-------|--------|-------------|
| `v2-blocks` | **Current** | Pipeline runs after the blocks-first refactor. Written by `FINALIZE_MOMENTS` from this point forward. |
| `v2-moments` | **Deprecated** | Legacy name written before the blocks abstraction was formalised. Accepted on read during the transition window; not written by any new pipeline run. |

**When it increments:** When the `moments_json` shape changes incompatibly, or when a
significant new pipeline generation is introduced. Bump requires a coordinated migration
(write new rows, migrate or expire old ones, update all query filters).

**Why `v2-moments` persisted past blocks launch:** `blocks_version` was added to track the
blocks schema independently, but the top-level `story_version` was never updated. The name
`v2-moments` became misleading once blocks replaced moments as the primary consumer output.
The rename to `v2-blocks` aligns the identifier with what consumers actually receive.

## `blocks_version`

Tracks the **blocks payload schema** — the structure of `blocks_json`, role vocabulary,
and guardrail rules in force when the blocks were generated.

| Value | Status | Description |
|-------|--------|-------------|
| `v1-blocks` | **Current** | First stable blocks schema: 4–7 blocks, roles from `BLOCK_ROLES`, narrative + key_play_ids per block. |

**When it increments:** When `blocks_json` shape changes incompatibly (e.g., new required
fields, role vocabulary changes, guardrail rule changes that alter structure). Independent
of `story_version` — a blocks-only refactor bumps only this field.

## Relationship between the two

`story_version` gates row selection. `blocks_version` gates blocks interpretation within a
selected row. A row can be current on `story_version` but stale on `blocks_version` if blocks
are regenerated independently (e.g., via the `backfill_embedded_tweets` path).

## Transition window: `v2-moments` → `v2-blocks`

Existing production rows carry `story_version = "v2-moments"`. During the transition:

1. New pipeline runs write `story_version = "v2-blocks"`.
2. All read-path query filters accept **both** values (`story_version IN ('v2-blocks', 'v2-moments')`).
3. When an existing `v2-moments` row is overwritten by a pipeline re-run, it is upgraded to `v2-blocks`.
4. After all rows are confirmed migrated (or expired), remove `_LEGACY_FLOW_VERSION` from the filter and drop the deprecated value from this doc.

The constants in code are:

```python
# api/app/services/pipeline/stages/finalize_moments.py
# api/app/routers/sports/game_timeline.py
# api/app/services/pipeline/backfill_embedded_tweets.py

FLOW_VERSION = "v2-blocks"          # written by new pipeline runs
_LEGACY_FLOW_VERSION = "v2-moments" # accepted on read only; remove after migration
```

## What consumers see

`story_version` and `blocks_version` are **internal DB fields**. They are not exposed in
any `/api/v1/` consumer response. The `ConsumerGameFlowResponse` shape in
`packages/js-core/src/api/games.ts` does not include these fields and need not change
when version strings are bumped.
