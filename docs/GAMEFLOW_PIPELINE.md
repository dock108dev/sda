# Game Flow Pipeline

Multi-stage pipeline for generating block-based game narratives from play-by-play data.

## Overview

The pipeline transforms raw PBP data into narrative game flows through 8 sequential stages. Each stage produces output consumed by the next stage.

```
NORMALIZE_PBP → GENERATE_MOMENTS → VALIDATE_MOMENTS → ANALYZE_DRAMA → GROUP_BLOCKS → RENDER_BLOCKS → VALIDATE_BLOCKS → FINALIZE_MOMENTS
```

**Location:** `api/app/services/pipeline/`

## Output: Blocks vs Moments

The pipeline produces **blocks** (consumer-facing narratives, 3-7 per game) and **moments** (internal traceability, 15-25 per game). See [GAMEFLOW_CONTRACT.md](GAMEFLOW_CONTRACT.md) for the authoritative specification of block fields, semantic roles, guardrail invariants, and narrative rules.

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

### 4. ANALYZE_DRAMA

**Purpose:** Use AI to identify the game's dramatic peak and assign quarter weights.

**Input:** Validated moments + game context
**Output:** Quarter weights for drama-weighted block distribution

**Implementation:** `stages/analyze_drama.py`

**How It Works:**
- OpenAI analyzes key plays and score progressions
- Identifies which quarter(s) contain the dramatic climax
- Returns weights like `{Q1: 1.0, Q2: 1.0, Q3: 1.5, Q4: 2.0}` for a late-game comeback
- Higher weights mean more blocks allocated to that quarter

**Usage:**
- Weights feed into GROUP_BLOCKS for drama-centered block distribution
- Ensures dramatic quarters get more narrative coverage
- Low-drama quarters can be condensed

### 5. GROUP_BLOCKS

**Purpose:** Group validated moments into 3-7 narrative blocks with semantic roles, using drama weights from ANALYZE_DRAMA.

**Input:** Validated moments
**Output:** Blocks with moment assignments and semantic roles

**Implementation:** `stages/group_blocks.py`

**Block Count Formula:**
```python
# Blowouts with minimal lead changes get 3 blocks
if is_blowout and lead_changes <= 1: return 3

base = 4
if lead_changes >= 3: base += 1
if lead_changes >= 6: base += 1
if total_plays > 400: base += 1
return min(base, 7)
```

**Semantic Roles:** SETUP → MOMENTUM_SHIFT → RESPONSE → DECISION_POINT → RESOLUTION (see [GAMEFLOW_CONTRACT.md](GAMEFLOW_CONTRACT.md) for definitions and constraints).

**Output Schema:**
```python
{
    "blocks_grouped": true,
    "blocks": [
        {
            "block_index": 0,
            "role": "SETUP",
            "moment_indices": [0, 1, 2],
            "score_before": [0, 0],
            "score_after": [15, 12],
            "key_play_ids": [5, 23, 41]
        },
        ...
    ],
    "block_count": 5,
    "lead_changes": 4
}
```

### 6. RENDER_BLOCKS

**Purpose:** Generate short narrative text for each block using OpenAI.

**Input:** Grouped blocks + play data
**Output:** Blocks with narrative text

**Implementation:** `stages/render_blocks.py`

**OpenAI Usage:**
- All blocks rendered in a single call
- Input per block: semantic role, score progression, key play descriptions, lead/margin context, top contributors from mini box
- Output: 1-5 sentences (~65 words) per block

**Prompt Context:**
- **Scores:** Score-before → score-after for each block
- **Lead context:** Human-readable margin change (e.g., "Hawks extend the lead to 8", "tie the game") — derived from `compute_lead_context()`
- **Contributors:** Block star players with delta stats (e.g., "Young +8 pts" for NBA, "Pastrnak +1g/+1a" for NHL) — derived from mini box data
- **Key plays:** Up to 3 play descriptions per block
- Lines are omitted when no scoring change occurs or no block stars exist

**Constraints:**
- OpenAI only writes prose - it does not decide block structure
- Each block narrative is role-aware
- Lead and contributor lines are narrative fuel, not to be quoted verbatim
- Forbidden phrases: "momentum", "turning point", "crucial", "clutch", etc.
- Play injection recovery has been removed — key plays are context, not mandatory references
- Narrative uses consequence-based importance: describe effects, not individual transactions

**Output Schema:**
```python
{
    "blocks_rendered": true,
    "blocks": [
        {
            "block_index": 0,
            "role": "SETUP",
            "narrative": "The Warriors jumped out to an early lead...",
            ...
        },
        ...
    ],
    "total_words": 210,
    "openai_calls": 1
}
```

### 7. VALIDATE_BLOCKS

**Purpose:** Validate blocks against guardrail invariants.

**Input:** Rendered blocks
**Output:** Validation status

**Implementation:** `stages/validate_blocks.py`

**Guardrail invariants and validation rules** are defined in [GAMEFLOW_CONTRACT.md §6](GAMEFLOW_CONTRACT.md). The pipeline enforces all invariants listed there.

### 8. FINALIZE_MOMENTS

**Purpose:** Persist completed game flow to database.

**Input:** Validated blocks + moments
**Output:** Persistence confirmation

**Implementation:** `stages/finalize_moments.py`

**Storage:**
- Table: `sports_game_stories`
- Columns: `moments_json`, `blocks_json`
- Version: `story_version = "v2-moments"`, `blocks_version = "v1-blocks"`
- Metadata: `moment_count`, `block_count`, `validated_at`

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
| `sports_game_stories` | Persisted game flow artifacts |

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
    "flow": {
        "moments": [...],
        "blocks": [
            {
                "blockIndex": 0,
                "role": "SETUP",
                "momentIndices": [0, 1, 2],
                "scoreBefore": [0, 0],
                "scoreAfter": [15, 12],
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

- [GAMEFLOW_CONTRACT.md](GAMEFLOW_CONTRACT.md) - Full game flow specification
- [API.md](API.md) - Complete API reference
