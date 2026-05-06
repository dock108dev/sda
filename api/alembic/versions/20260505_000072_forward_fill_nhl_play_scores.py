"""Forward-fill running scores on existing NHL plays.

The NHL API only emits homeScore/awayScore on goal events; every other play
(faceoff, shot, hit, ...) was persisted with NULL scores. Downstream
score-detection in the gameflow pipeline reads scores per-play and treats
None as 0, so every non-goal play immediately after a goal looked like a
phantom score reversal (1-0 → 0-0 → 1-0 → 0-0 ...). That broke flow
generation for NHL.

Going forward, the scraper forward-fills at PBP-normalization time so new
ingestions are correct. This migration heals already-stored rows by
forward-filling within each game in score order.

Idempotent: running it twice produces the same values (forward-filled
values match themselves, and the WHERE clause skips no-op updates).

Revision ID: 20260505_000072
Revises: 20260505_000071
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op

revision = "20260505_000072"
down_revision = "20260505_000071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MAX(...) OVER (... ROWS UNBOUNDED PRECEDING ... CURRENT ROW) ignores
    # NULLs by default in Postgres, and scores monotonically increase within
    # an NHL game, so MAX is equivalent to "last-known" forward-fill. Plays
    # before the first goal land on COALESCE(NULL, 0) = 0.
    op.execute(
        """
        WITH nhl_plays AS (
            SELECT p.id, p.game_id, p.play_index, p.home_score, p.away_score
            FROM sports_game_plays p
            JOIN sports_games g ON g.id = p.game_id
            JOIN sports_leagues l ON l.id = g.league_id
            WHERE l.code = 'NHL'
        ),
        filled AS (
            SELECT
                id,
                COALESCE(
                    MAX(home_score) OVER (
                        PARTITION BY game_id ORDER BY play_index
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ),
                    0
                ) AS new_home,
                COALESCE(
                    MAX(away_score) OVER (
                        PARTITION BY game_id ORDER BY play_index
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ),
                    0
                ) AS new_away
            FROM nhl_plays
        )
        UPDATE sports_game_plays p
        SET home_score = f.new_home,
            away_score = f.new_away
        FROM filled f
        WHERE p.id = f.id
          AND (
              p.home_score IS DISTINCT FROM f.new_home
              OR p.away_score IS DISTINCT FROM f.new_away
          )
        """
    )


def downgrade() -> None:
    # Cannot reverse — original NULLs were lossy. Best-effort: restore NULL
    # on plays whose home_score and away_score match the running prior-play
    # carry. Risky and rarely useful; leaving as a no-op.
    pass
