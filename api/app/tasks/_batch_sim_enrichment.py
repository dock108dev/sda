"""Post-simulation enrichment and analysis for batch simulation results.

Contains:
- Line analysis enrichment (closing line + current market line comparison)
- Batch summary computation and sanity warnings
- Prediction outcome persistence
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_MONEYLINE_KEYS = frozenset({"h2h", "moneyline"})


# ---------------------------------------------------------------------------
# Line analysis enrichment
# ---------------------------------------------------------------------------


def _match_closing_line_sides(
    lines: list,
    home_lower: str,
    away_lower: str,
) -> tuple[float | None, float | None]:
    """Match ClosingLine rows to home/away.

    ``ClosingLine.selection`` may be a literal ``"home"``/``"away"``
    (from ``SportsGameOdds.side``) or a team name string.  Tries
    explicit side labels first, then team-name substring matching.
    """
    home_price: float | None = None
    away_price: float | None = None

    for cl in lines:
        sel = cl.selection.lower().strip()
        # Explicit "home"/"away" labels (most common)
        if sel == "home":
            home_price = cl.price_american
            continue
        if sel == "away":
            away_price = cl.price_american
            continue
        # Team-name substring matching
        if home_lower in sel or sel in home_lower:
            home_price = cl.price_american
        elif away_lower in sel or sel in away_lower:
            away_price = cl.price_american

    # Fallback: if exactly 2 unmatched lines, assign by favorite/underdog
    # (lower price = favorite = more likely home in most datasets)
    if (home_price is None or away_price is None) and len(lines) >= 2:
        sorted_lines = sorted(lines, key=lambda cl: cl.price_american)
        home_price = sorted_lines[0].price_american
        away_price = sorted_lines[1].price_american

    return home_price, away_price


def _match_fairbet_sides(
    book_lines: list,
    home_lower: str,
    away_lower: str,
) -> tuple[float | None, float | None]:
    """Match FairbetGameOddsWork rows to home/away.

    ``selection_key`` uses the ``team:{slug}`` convention from
    ``build_selection_key()``.  Tries slug matching first, then
    falls back to substring matching on the raw key.
    """
    home_price: float | None = None
    away_price: float | None = None

    # Slugify team names for matching (replace spaces/special with _)
    home_slug = home_lower.replace(" ", "_").replace("-", "_")
    away_slug = away_lower.replace(" ", "_").replace("-", "_")

    for row in book_lines:
        sel = row.selection_key.lower()
        # Match "team:{slug}" format
        if home_slug in sel or home_lower in sel:
            home_price = row.price
        elif away_slug in sel or away_lower in sel:
            away_price = row.price

    # Fallback: assign by price (favorite first)
    if (home_price is None or away_price is None) and len(book_lines) >= 2:
        sorted_lines = sorted(book_lines, key=lambda r: r.price)
        home_price = sorted_lines[0].price
        away_price = sorted_lines[1].price

    return home_price, away_price


async def enrich_with_closing_lines(
    db: AsyncSession,
    sim_results: list[dict],
) -> None:
    """Batch-lookup market lines and add line analysis to each game result.

    - **Final games** use closing lines from ``ClosingLine`` (captured at
      game-start transition).
    - **Future games** use current market lines from ``FairbetGameOddsWork``
      (the live odds work table).
    - Games with no line data in either table simply get no ``line_analysis``
      key — the frontend omits the section.

    For each game with line data, computes:
    - Raw market prices (American odds)
    - Devigged (no-vig) market probability
    - Model probability vs market edge
    - Model's fair American line (with ~2% vig via Shin)
    - EV% if betting the model's side at the market price

    Mutates ``sim_results`` in-place, adding a ``line_analysis`` key.
    """
    from app.db.odds import ClosingLine, FairbetGameOddsWork
    from app.services.ev import (
        american_to_implied,
        calculate_ev,
        prob_to_vigged_american,
        remove_vig,
    )

    game_ids = [r["game_id"] for r in sim_results if "game_id" in r]
    if not game_ids:
        return

    # 1. Batch-load closing lines (Pinnacle)
    cl_stmt = (
        select(ClosingLine)
        .where(
            ClosingLine.game_id.in_(game_ids),
            ClosingLine.market_key.in_(_MONEYLINE_KEYS),
            ClosingLine.provider == "Pinnacle",
        )
    )
    cl_result = await db.execute(cl_stmt)
    closing_lines = list(cl_result.scalars().all())

    cl_by_game: dict[int, list] = {}
    for cl in closing_lines:
        cl_by_game.setdefault(cl.game_id, []).append(cl)

    # 2. For games WITHOUT closing lines, try current market odds
    games_without_cl = [gid for gid in game_ids if gid not in cl_by_game]
    current_by_game: dict[int, list] = {}

    if games_without_cl:
        fb_stmt = (
            select(FairbetGameOddsWork)
            .where(
                FairbetGameOddsWork.game_id.in_(games_without_cl),
                FairbetGameOddsWork.market_key.in_(_MONEYLINE_KEYS),
                FairbetGameOddsWork.book == "Pinnacle",
            )
        )
        fb_result = await db.execute(fb_stmt)
        fb_rows = list(fb_result.scalars().all())

        if not fb_rows:
            fb_stmt = (
                select(FairbetGameOddsWork)
                .where(
                    FairbetGameOddsWork.game_id.in_(games_without_cl),
                    FairbetGameOddsWork.market_key.in_(_MONEYLINE_KEYS),
                )
            )
            fb_result = await db.execute(fb_stmt)
            fb_rows = list(fb_result.scalars().all())

        for row in fb_rows:
            current_by_game.setdefault(row.game_id, []).append(row)

    # 3. Process each game result
    for game_result in sim_results:
        gid = game_result.get("game_id")
        model_home_wp = game_result.get("home_win_probability")
        if model_home_wp is None:
            continue

        home_team = game_result.get("home_team", "")
        away_team = game_result.get("away_team", "")
        home_lower = home_team.lower()
        away_lower = away_team.lower()

        home_price: float | None = None
        away_price: float | None = None
        line_type = "closing"
        provider = "Pinnacle"

        if gid in cl_by_game:
            lines = cl_by_game[gid]
            home_price, away_price = _match_closing_line_sides(
                lines, home_lower, away_lower,
            )
            provider = "Pinnacle"

        elif gid in current_by_game:
            lines = current_by_game[gid]
            books = {row.book for row in lines}
            chosen_book = "Pinnacle" if "Pinnacle" in books else sorted(books)[0]
            book_lines = [r for r in lines if r.book == chosen_book]
            home_price, away_price = _match_fairbet_sides(
                book_lines, home_lower, away_lower,
            )
            line_type = "current"
            provider = chosen_book

        if home_price is None or away_price is None:
            continue

        try:
            implied_home = american_to_implied(home_price)
            implied_away = american_to_implied(away_price)
            true_probs = remove_vig([implied_home, implied_away])
            market_home_wp = true_probs[0]
            market_away_wp = true_probs[1]
        except (ValueError, ZeroDivisionError):
            continue

        model_away_wp = 1.0 - model_home_wp
        home_edge = model_home_wp - market_home_wp
        away_edge = model_away_wp - market_away_wp

        model_home_line = round(prob_to_vigged_american(model_home_wp))
        model_away_line = round(prob_to_vigged_american(model_away_wp))

        home_ev = round(calculate_ev(home_price, model_home_wp), 2)
        away_ev = round(calculate_ev(away_price, model_away_wp), 2)

        game_result["line_analysis"] = {
            "market_home_ml": round(home_price),
            "market_away_ml": round(away_price),
            "market_home_wp": round(market_home_wp, 4),
            "market_away_wp": round(market_away_wp, 4),
            "model_home_wp": round(model_home_wp, 4),
            "model_away_wp": round(model_away_wp, 4),
            "home_edge": round(home_edge, 4),
            "away_edge": round(away_edge, 4),
            "model_home_line": model_home_line,
            "model_away_line": model_away_line,
            "home_ev_pct": home_ev,
            "away_ev_pct": away_ev,
            "provider": provider,
            "line_type": line_type,
        }


# ---------------------------------------------------------------------------
# Batch summary and sanity checks
# ---------------------------------------------------------------------------


def build_batch_summary(
    sim_results: list[dict],
) -> tuple[dict | None, list[str]]:
    """Compute batch-level summary stats and sanity warnings."""
    success = [r for r in sim_results if "error" not in r and r.get("home_win_probability") is not None]
    if not success:
        return None, []

    n = len(success)
    avg_home_score = sum(r.get("average_home_score", 0) or 0 for r in success) / n
    avg_away_score = sum(r.get("average_away_score", 0) or 0 for r in success) / n
    home_wins = sum(1 for r in success if (r.get("home_win_probability", 0) or 0) > 0.5)

    wp_dist = {"50-55": 0, "55-60": 0, "60-70": 0, "70+": 0}
    for r in success:
        wp = max(r.get("home_win_probability", 0) or 0, r.get("away_win_probability", 0) or 0) * 100
        if wp >= 70:
            wp_dist["70+"] += 1
        elif wp >= 60:
            wp_dist["60-70"] += 1
        elif wp >= 55:
            wp_dist["55-60"] += 1
        else:
            wp_dist["50-55"] += 1

    event_summaries = [r.get("event_summary") for r in success if r.get("event_summary")]
    avg_pa = 0.0
    if event_summaries:
        avg_pa = sum(
            (es.get("home", {}).get("avg_pa", 0) + es.get("away", {}).get("avg_pa", 0)) / 2
            for es in event_summaries
        ) / len(event_summaries)

    batch_summary = {
        "avg_runs_per_team": round((avg_home_score + avg_away_score) / 2, 1),
        "avg_total_per_game": round(avg_home_score + avg_away_score, 1),
        "avg_pa_per_team": round(avg_pa, 1) if avg_pa else None,
        "home_win_rate": round(home_wins / n, 3),
        "wp_distribution": wp_dist,
    }

    from app.analytics.core.simulation_analysis import check_batch_sanity
    aggregate_events = _aggregate_event_summaries(event_summaries) if event_summaries else None
    warnings = check_batch_sanity(success, aggregate_events)

    return batch_summary, warnings


def _aggregate_event_summaries(
    summaries: list[dict],
) -> dict:
    """Average per-game event summaries into a single batch-level summary."""
    n = len(summaries)
    if n == 0:
        return {}

    def _avg_team(side: str) -> dict:
        teams = [s.get(side, {}) for s in summaries]
        avg = lambda key: round(sum(t.get(key, 0) for t in teams) / n, 1)  # noqa: E731
        rates = [t.get("pa_rates", {}) for t in teams]
        avg_rate = lambda key: round(sum(r.get(key, 0) for r in rates) / n, 3)  # noqa: E731
        return {
            "avg_pa": avg("avg_pa"),
            "avg_hits": avg("avg_hits"),
            "avg_hr": avg("avg_hr"),
            "avg_bb": avg("avg_bb"),
            "avg_k": avg("avg_k"),
            "avg_runs": avg("avg_runs"),
            "pa_rates": {
                "k_pct": avg_rate("k_pct"),
                "bb_pct": avg_rate("bb_pct"),
                "single_pct": avg_rate("single_pct"),
                "double_pct": avg_rate("double_pct"),
                "triple_pct": avg_rate("triple_pct"),
                "hr_pct": avg_rate("hr_pct"),
                "out_pct": avg_rate("out_pct"),
            },
        }

    games = [s.get("game", {}) for s in summaries]
    avg_game = lambda key: round(sum(g.get(key, 0) for g in games) / n, 3)  # noqa: E731

    return {
        "home": _avg_team("home"),
        "away": _avg_team("away"),
        "game": {
            "avg_total_runs": round(sum(g.get("avg_total_runs", 0) for g in games) / n, 1),
            "median_total_runs": round(sum(g.get("median_total_runs", 0) for g in games) / n, 0),
            "extra_innings_pct": avg_game("extra_innings_pct"),
            "shutout_pct": avg_game("shutout_pct"),
            "one_run_game_pct": avg_game("one_run_game_pct"),
        },
    }


# ---------------------------------------------------------------------------
# Prediction outcome persistence
# ---------------------------------------------------------------------------


async def save_prediction_outcomes(
    db: AsyncSession,
    batch_sim_job_id: int,
    sport: str,
    probability_mode: str,
    results: list[dict],
    games_by_id: dict | None = None,
) -> None:
    """Persist per-game predictions; immediately record outcomes for final games."""
    from app.db.analytics import AnalyticsPredictionOutcome

    for game_result in results:
        if "error" in game_result or "home_win_probability" not in game_result:
            continue

        outcome = AnalyticsPredictionOutcome(
            game_id=game_result["game_id"],
            sport=sport,
            batch_sim_job_id=batch_sim_job_id,
            home_team=game_result["home_team"],
            away_team=game_result["away_team"],
            predicted_home_wp=game_result["home_win_probability"],
            predicted_away_wp=game_result["away_win_probability"],
            predicted_home_score=game_result.get("average_home_score"),
            predicted_away_score=game_result.get("average_away_score"),
            probability_mode=probability_mode,
            game_date=game_result.get("game_date"),
            sim_wp_std_dev=game_result.get("home_wp_std_dev"),
            sim_iterations=game_result.get("iterations"),
            sim_score_std_home=game_result.get("score_std_home"),
            sim_score_std_away=game_result.get("score_std_away"),
            profile_games_home=game_result.get("profile_games_home"),
            profile_games_away=game_result.get("profile_games_away"),
            sim_probability_source=game_result.get("probability_source"),
            feature_snapshot=game_result.get("feature_snapshot"),
        )

        game = games_by_id.get(game_result["game_id"]) if games_by_id else None
        if (
            game is not None
            and game.status in ("final", "archived")
            and game.home_score is not None
            and game.away_score is not None
        ):
            home_win_actual = game.home_score > game.away_score
            predicted_home_win = outcome.predicted_home_wp > 0.5
            actual = 1.0 if home_win_actual else 0.0

            outcome.actual_home_score = game.home_score
            outcome.actual_away_score = game.away_score
            outcome.home_win_actual = home_win_actual
            outcome.correct_winner = predicted_home_win == home_win_actual
            outcome.brier_score = round((outcome.predicted_home_wp - actual) ** 2, 6)
            outcome.outcome_recorded_at = datetime.now(UTC)

        db.add(outcome)
