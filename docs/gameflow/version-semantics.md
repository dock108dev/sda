# Game Flow Version Semantics

Three independent version strings live on every `SportsGameFlow` row.

## `story_version`

Tracks the **overall pipeline schema** — the structure of `moments_json`,
how plays are grouped, and which pipeline stages produced the row. It is
the primary discriminator used by query filters to select the "current
generation" of flows.

| Value | Status | Description |
|-------|--------|-------------|
| `v2-blocks` | **Current** | Pipeline runs after the blocks-first refactor. Written by `FINALIZE_MOMENTS` on every new flow. |

**When it increments:** When the `moments_json` shape changes
incompatibly, or when a significant new pipeline generation is introduced.
Bumping requires a coordinated migration: write new rows, migrate or expire
old ones, update all query filters.

## `blocks_version`

Tracks the **blocks payload schema** — the structure of `blocks_json`,
role vocabulary, and guardrail rules in force when the blocks were
generated.

| Value | Status | Description |
|-------|--------|-------------|
| `v1-blocks` | **Current** | First stable blocks schema: 3–7 blocks, `role` from `BLOCK_ROLES`, `story_role` from `VALID_STORY_ROLES`, narrative + key_play_ids per block, plus the segmentation/voice fields (`leverage`, `score_context`, `featured_players`, `period_range`). |

**When it increments:** When `blocks_json` shape changes incompatibly
(new required fields, role vocabulary changes, guardrail rule changes
that alter structure). Independent of `story_version` — a blocks-only
refactor bumps only this field.

## `version` (top-level schema literal)

Tracks the **top-level row schema** — the set of columns the consumer
endpoints serialize. Consumers see this on `GameFlowResponse.version` and
can branch on it for forward-compatibility.

| Value | Status | Description |
|-------|--------|-------------|
| `game-flow-v2` | **Current** | Carries the v2 top-level fields: `archetype`, `winner_team_id`, `source_counts`, `validation`, plus the v3 segmentation/voice fields on each block. |

**When it increments:** When the top-level row gains or loses columns the
consumer schema has to know about.

## Relationship between the three

`story_version` gates row selection. `blocks_version` gates blocks
interpretation within a selected row. `version` is the wire-level
literal serialized to consumers. A row can be current on `story_version`
but stale on `blocks_version` if blocks are regenerated independently
(e.g., via the `backfill_embedded_tweets` path).

## Constants in code

```python
# api/app/services/pipeline/stages/finalize_moments.py
# api/app/routers/sports/game_timeline.py
# api/app/services/pipeline/backfill_embedded_tweets.py

FLOW_VERSION = "v2-blocks"      # SportsGameFlow.story_version
BLOCKS_VERSION = "v1-blocks"    # SportsGameFlow.blocks_version
SCHEMA_VERSION_V2 = "game-flow-v2"  # SportsGameFlow.version (consumer-visible)
```

`FLOW_VERSION` is part of the upsert key on `SportsGameFlow` — read paths
filter on it to ignore stale generations. `SCHEMA_VERSION_V2` is the literal
stamped on the consumer-facing row.

## What consumers see

`story_version` and `blocks_version` are **internal DB fields**. They are
not exposed in any `/api/v1/` consumer response.

`version` (the `game-flow-v2` literal) **is** exposed on
`GameFlowResponse.version` so consumers can branch on it. The consumer
schema also exposes `archetype`, `winnerTeamId`, `sourceCounts`, and
`validation` alongside it.
