# JSONB Column Schema Inventory

Pipeline-relevant JSONB columns, their validation schemas, and enforcement points.

## Pipeline-relevant columns

These columns are read or written by one or more of the 8 narrative pipeline stages
(`NORMALIZE_PBP` → `FINALIZE_MOMENTS`).  Each has a JSON Schema draft-7 file under
`api/app/db/schemas/jsonb/` and a corresponding Pydantic model in
`api/app/db/jsonb_registry.py`.  SQLAlchemy mapper event hooks (in
`api/app/db/jsonb_validators.py`) enforce the schema on every INSERT and UPDATE.

| Table | Column | JSON Schema file | Pydantic class | Top-level type | Nullable |
|-------|--------|-----------------|----------------|---------------|----------|
| `sports_game_stories` | `moments_json` | `moments_json.json` | `MomentsJsonSchema` | array | yes |
| `sports_game_stories` | `blocks_json` | `blocks_json.json` | `BlocksJsonSchema` | array | yes |
| `sports_game_pipeline_stages` | `output_json` | `pipeline_stage_output_json.json` | `DictJsonSchema` | object | yes |
| `sports_game_pipeline_stages` | `logs_json` | `pipeline_stage_logs_json.json` | `PipelineLogsJsonSchema` | array | no (default `[]`) |
| `sports_game_timeline_artifacts` | `timeline_json` | `timeline_json.json` | `ListOfDictsSchema` | array | no (default `[]`) |
| `sports_game_timeline_artifacts` | `game_analysis_json` | `game_analysis_json.json` | `DictJsonSchema` | object | no (default `{}`) |
| `sports_game_timeline_artifacts` | `summary_json` | `summary_json.json` | `DictJsonSchema` | object | no (default `{}`) |

## Non-pipeline JSONB columns (also validated)

These columns are not directly touched by pipeline stages but are validated at the
ORM layer for structural integrity.

| Table | Column | JSON Schema file | Pydantic class | Top-level type | Nullable |
|-------|--------|-----------------|----------------|---------------|----------|
| `sports_games` | `external_ids` | `external_ids.json` | `ExternalIdsSchema` | object (flat `str→str\|int`) | no (default `{}`) |
| `sports_teams` | `external_codes` | `external_ids.json` | `ExternalIdsSchema` | object (flat `str→str\|int`) | no (default `{}`) |
| `sports_team_boxscores` | `raw_stats_json` | — | `DictJsonSchema` | object | yes |
| `sports_player_boxscores` | `raw_stats_json` | — | `DictJsonSchema` | object | yes |
| `sports_game_plays` | `raw_data` | — | `DictJsonSchema` | object | yes |

## Column detail

### `sports_game_stories.moments_json`

Written by `FINALIZE_MOMENTS` (`api/app/services/pipeline/stages/finalize_moments.py`).

```json
[
  {
    "play_ids": [0, 1, 2],
    "explicitly_narrated_play_ids": [1],
    "period": 1,
    "start_clock": "12:00",
    "end_clock": "9:43",
    "score_before": [0, 0],
    "score_after": [3, 2]
  }
]
```

**Required item fields:** `play_ids` (array of integer).  All other fields are optional.

**Postgres CHECK:** `moments_json IS NULL OR jsonb_typeof(moments_json) = 'array'`

---

### `sports_game_stories.blocks_json`

Written by `FINALIZE_MOMENTS`; validated by `VALIDATE_BLOCKS`.

```json
[
  {
    "block_index": 0,
    "role": "SETUP",
    "narrative": "The Lakers jumped out early...",
    "moment_indices": [0, 1],
    "play_ids": [0, 1, 2, 3],
    "key_play_ids": [1, 3],
    "period_start": 1,
    "period_end": 1,
    "score_before": [0, 0],
    "score_after": [14, 10],
    "mini_box": {"cumulative": {"home": {"points": 14}, "away": {"points": 10}}, "delta": {"home": {"points": 14}, "away": {"points": 10}}},
    "peak_margin": 6,
    "peak_leader": 1,
    "embedded_social_post_id": null
  }
]
```

**Required item fields:** `block_index` (int ≥ 0), `role` (one of `SETUP | MOMENTUM_SHIFT | RESPONSE | DECISION_POINT | RESOLUTION`), `narrative` (non-empty string).

**Postgres CHECK:** `blocks_json IS NULL OR jsonb_typeof(blocks_json) = 'array'`

---

### `sports_game_pipeline_stages.output_json`

Written at the end of each pipeline stage.  Shape varies by stage; only top-level type (object) is enforced.

**Postgres CHECK:** `output_json IS NULL OR jsonb_typeof(output_json) = 'object'`

---

### `sports_game_pipeline_stages.logs_json`

Appended to by `GamePipelineStage.add_log()` throughout stage execution.

```json
[
  {"timestamp": "2026-04-20T12:00:00+00:00", "level": "info", "message": "Stage started"},
  {"timestamp": "2026-04-20T12:00:01+00:00", "level": "warning", "message": "Low coverage"}
]
```

**Required item fields:** `timestamp` (string), `level` (one of `info | warning | error | debug`), `message` (non-empty string).

**Postgres CHECK:** `jsonb_typeof(logs_json) = 'array'`

---

### `sports_game_timeline_artifacts.timeline_json`

Reserved for future timeline feature.  Currently always written as `[]`.

**Postgres CHECK:** `jsonb_typeof(timeline_json) = 'array'`

---

### `sports_game_timeline_artifacts.game_analysis_json`

Reserved for future analysis feature.  Currently always written as `{}`.

**Postgres CHECK:** `jsonb_typeof(game_analysis_json) = 'object'`

---

### `sports_game_timeline_artifacts.summary_json`

Reserved for future summary feature.  Currently always written as `{}`.

**Postgres CHECK:** `jsonb_typeof(summary_json) = 'object'`

## Validation layers

1. **App layer (primary)** — Pydantic schemas in `jsonb_registry.py` validate every write
   before SQL is issued.  Raises `JsonbValidationError` (subclass of `ValueError`) naming
   the column and violated constraint.

2. **Postgres CHECK constraints (secondary guard)** — `jsonb_typeof(...)` checks enforce
   top-level structural sanity for any write that bypasses the ORM (migrations, `psql`,
   ETL).  Applied by migration `20260420_000054_add_pipeline_jsonb_check_constraints`.

3. **JSON Schema files (specification)** — Draft-7 files in `api/app/db/schemas/jsonb/`
   are the authoritative spec.  Pydantic models are hand-translated from these files;
   keep them in sync when schemas evolve.
