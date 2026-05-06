# Game Flow Pipeline

Multi-stage pipeline for generating block-based game narratives from play-by-play data.

## Overview

The pipeline transforms raw PBP data into narrative game flows through 9 sequential stages. Each stage produces output consumed by the next stage.

```
NORMALIZE_PBP → GENERATE_MOMENTS → VALIDATE_MOMENTS → CLASSIFY_GAME_SHAPE → ANALYZE_DRAMA → GROUP_BLOCKS → RENDER_BLOCKS → VALIDATE_BLOCKS → FINALIZE_MOMENTS
```

**Location:** `api/app/services/pipeline/`

## Output: Blocks vs Moments

The pipeline produces **blocks** (consumer-facing narratives, 3-7 per game) and **moments** (internal traceability, 15-25 per game). See [Game Flow Contract](contract.md) for the authoritative specification of block fields, semantic roles, guardrail invariants, and narrative rules.

## Stages

### 1. NORMALIZE_PBP

**Purpose:** Fetch and normalize play-by-play data from the database.

**Input:** Game ID
**Output:** Normalized plays with phase assignments, synthetic timestamps, score states

**Implementation:** `stages/normalize_pbp.py`

**Output Schema:**
```python
{
    "pbp_events": [...],        # Normalized play records
    "game_start": "...",        # ISO datetime
    "game_end": "...",          # ISO datetime
    "has_overtime": bool,
    "total_plays": int,
    "phase_boundaries": {...}   # Phase → (start, end) times
}
```

### 2. GENERATE_MOMENTS

**Purpose:** Segment PBP into moments with explicit narration targets.

**Input:** Normalized PBP events
**Output:** Ordered list of moments with play assignments

**Implementation:** `stages/generate_moments.py`

**Segmentation Rules:**
- Moments are contiguous sets of plays (typically 15-50 plays per moment)
- Hard boundaries: period ends, large lead changes (6+ points)
- Soft boundaries: timeouts, stoppages, scoring plays (after minimum threshold)
- No play appears in multiple moments
- Each moment has 1-5 explicitly narrated plays

### 3. VALIDATE_MOMENTS

**Purpose:** Validate moment structure against requirements.

**Input:** Generated moments + normalized plays
**Output:** Validation status and any errors

**Implementation:** `stages/validate_moments.py`

**Validation Rules:**
1. Non-empty `play_ids` in each moment
2. Non-empty `explicitly_narrated_play_ids` (subset of `play_ids`)
3. No overlapping plays between moments
4. Canonical ordering by play_index
5. All play references exist in PBP data

### 4. CLASSIFY_GAME_SHAPE

**Purpose:** Deterministically classify the game's archetype before any drama-weighting or block allocation runs.

**Input:** Validated moments + normalized PBP events
**Output:** Archetype label (one of `wire_to_wire`, `comeback`, `back_and_forth`, `blowout`, `early_avalanche_blowout`, `low_event`, `fake_close`, `late_separation`)

**Implementation:** `stages/classify_game_shape.py`

**How It Works:**
- Pure-Python rules over the per-play `ScoreTimeline` and PBP events
- Priority order: `low_event` → `comeback` → `fake_close` → `blowout` → `back_and_forth` → `late_separation` → `wire_to_wire`
- No LLM call

**Usage:**
- Drives drama weighting in ANALYZE_DRAMA
- Drives blowout compression and archetype-required pivots in GROUP_BLOCKS
- Drives prompt framing in RENDER_BLOCKS

### 5. ANALYZE_DRAMA

**Purpose:** Compute deterministic per-quarter drama weights from the archetype + per-quarter score signals.

**Input:** Validated moments + archetype from CLASSIFY_GAME_SHAPE
**Output:** Quarter weights for drama-weighted block distribution

**Implementation:** `stages/analyze_drama.py`

**How It Works:**
- Pure-Python `compute_drama_weights(archetype, quarter_summary, league)` mapping
- Wire-to-wire amplifies the opening lead-creation period; suppresses middle/late
- Comeback amplifies the highest-swing turning period; suppresses Q1 unless Q1 *is* the turning period
- Blowout / early-avalanche emphasize the decisive period; compress late
- Back-and-forth and low-event use even weights
- Fake-close and late-separation amplify the final period
- Output is clamped to `[0.5, 2.5]` to match the range expected by `weighted_splits.find_weighted_split_points`
- No LLM call

**Usage:**
- Weights feed into GROUP_BLOCKS for drama-centered block distribution
- Dramatic quarters get more narrative coverage; low-drama quarters can be condensed

### 6. GROUP_BLOCKS

**Purpose:** Group validated moments into 3-7 narrative blocks with semantic roles, using drama weights from ANALYZE_DRAMA.

**Input:** Validated moments
**Output:** Blocks with moment assignments and semantic roles

**Implementation:** `stages/group_blocks.py`

**Block count rule:** archetype-driven, with a fallback formula for
generic shapes. See `group_helpers.compute_block_count`.

```python
# Archetype shapes drive the floor first.
if archetype in {"blowout", "early_avalanche_blowout", "low_event"}:
    return MIN_BLOCKS  # 3

# Otherwise, lead-change + play-count formula.
base = 4
if lead_changes >= 3: base += 1
if lead_changes >= 6: base += 1
if total_plays > 400: base += 1
return min(base, MAX_BLOCKS)  # capped at 7
```

**Structural roles** (`role`): SETUP → MOMENTUM_SHIFT → RESPONSE →
DECISION_POINT → RESOLUTION. Assigned by `group_roles.assign_roles`.

**Narrative beats** (`story_role`): assigned by
`segment_classification.classify_blocks` after structural roles. Adjacent
low-leverage middle blocks of a blowout are then merged via
`merge_blowout_compression` so the consumer sees one
`blowout_compression` block instead of three quiet ones.

See [Game Flow Contract](contract.md) for the full role / story_role /
leverage vocabulary.

**Output Schema:**
```python
{
    "blocks_grouped": true,
    "blocks": [
        {
            "block_index": 0,
            "role": "SETUP",
            "story_role": "opening",
            "leverage": "low",
            "period_range": "Q1 12:00–6:39",
            "moment_indices": [0, 1, 2],
            "score_before": [0, 0],
            "score_after": [15, 12],
            "score_context": {"lead_change": false, "largest_lead_delta": 3},
            "key_play_ids": [5, 23, 41]
        },
        ...
    ],
    "block_count": 5,
    "lead_changes": 4
}
```

### 7. RENDER_BLOCKS

**Purpose:** Generate short narrative text for each block using OpenAI.

**Input:** Grouped blocks + play data
**Output:** Blocks with narrative text

**Implementation:** `stages/render_blocks.py`, with prompt construction in
`stages/render_prompts.py` and featured-player derivation in
`stages/featured_players_v3.py`.

**OpenAI Usage:**
- One block-render call (all blocks in a single completion), then a
  game-level flow pass that smooths transitions while preserving facts.
- Input per block: structural role, `story_role`, `leverage`,
  per-segment evidence, featured-player anchors, mini-box deltas, and
  the score-progression line.
- Output: 1-5 sentences (~65 words) per block.

**Prompt Context:**
- **Scores:** Score-before → score-after for each block.
- **Story-role guidance:** Beat-specific instructions injected per block
  (e.g., a `turning_point` block is told to describe the separation, a
  `closeout` block is told to describe how the game ended).
- **Featured players:** Up to 2 per block with structured `reason`
  strings derived from the segment evidence; the prompt allows the
  renderer to lean on these as proof rather than decoration.
- **Per-segment evidence:** Structured key-play descriptions per block,
  replacing the older undifferentiated play list.
- **Mini-box contributors:** Top players with delta stats (`+8 pts`,
  `+1g/+1a`) — narrative fuel, not direct quotes.
- Lines are omitted when no scoring change occurs or no anchors exist.

**Constraints:**
- OpenAI only writes prose — it does not decide block structure or
  story_role.
- Each block narrative is role-aware *and* story_role-aware.
- Forbidden phrases: see `render_validation.BANNED_PHRASES` (locked by
  `tests/test_banned_phrases.py`).
- Narrative uses consequence-based importance: describe effects, not
  individual transactions.

**Output Schema:**
```python
{
    "blocks_rendered": true,
    "blocks": [
        {
            "block_index": 0,
            "role": "SETUP",
            "story_role": "opening",
            "leverage": "low",
            "narrative": "The Warriors jumped out to an early lead...",
            "featured_players": [
                {"name": "Curry", "team_abbr": "GSW", "reason": "..."}
            ],
            ...
        },
        ...
    ],
    "total_words": 210,
    "openai_calls": 2
}
```

### 8. VALIDATE_BLOCKS

**Purpose:** Validate blocks against guardrail invariants.

**Input:** Rendered blocks
**Output:** Validation status

**Implementation:** `stages/validate_blocks.py` orchestrates rule
modules:

- `validate_blocks_rules.py` — structural / stylistic checks (block
  count, role positions, score continuity, word counts, etc.)
- `validate_blocks_segments.py` — archetype-aware language gates
  (Rule 13 late-blowout leverage, Rule 14 low-event drama)
- `validate_blocks_voice.py` — v3 voice contract (Rule 17 no repeated
  final score, Rule 18 featured players have reason, Rule 19
  story_role present)

**Guardrail invariants and validation rules** are defined in
[Game Flow Contract §6](contract.md). The pipeline enforces all
invariants listed there.

### 9. FINALIZE_MOMENTS

**Purpose:** Persist completed game flow to database.

**Input:** Validated blocks + moments
**Output:** Persistence confirmation

**Implementation:** `stages/finalize_moments.py`

**Storage:**
- Table: `sports_game_stories` (ORM: `SportsGameFlow` in `api/app/db/flow.py`)
- JSONB columns: `moments_json`, `blocks_json`
- Versions: `story_version = "v2-blocks"`, `blocks_version = "v1-blocks"`,
  `version = "game-flow-v2"` (top-level row stamp). See
  [Version Semantics](version-semantics.md).
- Metadata: `moment_count`, `block_count`, `archetype`, `winner_team_id`,
  `source_counts`, `validation`, `validated_at`

## Pipeline Execution

### API Endpoints

**Base path:** `/api/admin/sports/pipeline`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/{game_id}/start` | POST | Create a new pipeline run |
| `/{game_id}/rerun` | POST | Create new run + optionally execute stages |
| `/{game_id}/run-full` | POST | Full pipeline in one request |
| `/run/{run_id}` | GET | Get run status with all stages |
| `/run/{run_id}/execute/{stage}` | POST | Execute a specific stage |
| `/game/{game_id}` | GET | List runs for a game |
| `/bulk-generate-async` | POST | Start async bulk generation (Celery) |
| `/backfill-embedded-tweets` | POST | Backfill social post references into existing flows |

### Database Tables

| Table | Purpose |
|-------|---------|
| `sports_game_pipeline_runs` | Pipeline execution records |
| `sports_game_pipeline_stages` | Per-stage output and logs |
| `sports_game_stories` | Persisted game flow artifacts (ORM: `SportsGameFlow`) |

### Execution Modes

**Auto-chain:** All stages run sequentially without pause.
**Manual:** Each stage requires explicit advancement (for debugging).

## Game Flow Output

The final game flow contains both blocks (consumer-facing) and moments (traceability).

### API Access

```
GET /api/admin/sports/games/{game_id}/flow
```

Returns:

```json
{
    "gameId": 123,
    "version": "game-flow-v2",
    "archetype": "comeback",
    "winnerTeamId": "LAL",
    "flow": {
        "moments": [...],
        "blocks": [
            {
                "blockIndex": 0,
                "role": "SETUP",
                "storyRole": "opening",
                "leverage": "low",
                "periodRange": "Q1 12:00–6:39",
                "momentIndices": [0, 1, 2],
                "scoreBefore": {"home": 0, "away": 0},
                "scoreAfter": {"home": 15, "away": 12},
                "scoreContext": {"leadChange": false, "largestLeadDelta": 3},
                "featuredPlayers": [
                    {"name": "Curry", "teamAbbr": "GSW", "reason": "8 points on 4 of 5 to open"}
                ],
                "narrative": "The Warriors jumped out to an early lead..."
            }
        ]
    },
    "plays": [...],
    "validationPassed": true
}
```

**Primary view:** Use `blocks` for consumer-facing game summaries.
**Traceability:** Use `moments` to link narratives back to specific plays.

## Key Principles

1. **Blocks are consumer-facing** - 3-7 blocks per game, 60-90 second read time
2. **Moments enable traceability** - Every block maps to underlying plays
3. **Segmentation is mechanical** - Block grouping is deterministic, not AI-driven
4. **OpenAI is prose-only** - It renders narratives, not structure
5. **Guardrails are non-negotiable** - Violations fail the pipeline

## See Also

- [Game Flow Contract](contract.md) - Full game flow specification
- [API Reference](../api.md) - Complete API reference
