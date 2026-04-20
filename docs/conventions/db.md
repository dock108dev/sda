# DB Conventions

## FK ondelete decision matrix

Every `ForeignKey(...)` in `api/app/db/` and `api/alembic/versions/` must
declare an explicit `ondelete=` strategy. The CI job `lint-fk-ondelete` enforces
this on every PR touching those paths.

| Relationship class | Strategy | Rationale |
|--------------------|----------|-----------|
| Child-of-game (boxscore, PBP, pipeline run, odds snapshot, flow) | `CASCADE` | Row is meaningless without the parent game |
| Child-of-tournament (golf leaderboard, rounds, odds, DFS projections, field entries) | `CASCADE` | Row is meaningless without the parent tournament |
| Join / association table (pool_bucket_player, pool_pick, etc.) | `CASCADE` | Removing either side of the join should remove the association |
| Nullable soft-reference (PBP `team_id`, PBP `player_ref_id`, player `team_id`) | `SET NULL` | The row remains valid without the referenced lookup; foreign key is nullable |
| Lookup / reference table (league, sport, book) | `RESTRICT` | Deleting a lookup used by live rows is a data-integrity error that should be blocked |
| Audit / log row that references a pipeline run or scrape run | `SET NULL` | The audit row should survive run cleanup |

## Examples

```python
# child-of-game → CASCADE
game_id: Mapped[int] = mapped_column(
    Integer, ForeignKey("sports_games.id", ondelete="CASCADE"), nullable=False
)

# nullable soft-reference → SET NULL
team_id: Mapped[int | None] = mapped_column(
    Integer, ForeignKey("sports_teams.id", ondelete="SET NULL"), nullable=True
)

# lookup reference → RESTRICT
league_id: Mapped[int] = mapped_column(
    Integer, ForeignKey("sports_leagues.id", ondelete="RESTRICT"), nullable=False
)
```

## Adding a new FK

1. Pick a strategy from the matrix above.
2. Add `ondelete=` to the `ForeignKey(...)` call.
3. Run `python scripts/lint_fk_ondelete.py` locally to confirm no violations.
4. The `lint-fk-ondelete` CI job will enforce this automatically on PR.
