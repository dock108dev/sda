"""Compute derived metrics for sports games."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..db.odds import SportsGameOdds
from ..db.sports import SportsGame, SportsTeam


def _select_closing_lines(
    odds: Sequence[SportsGameOdds], market: str
) -> list[SportsGameOdds]:
    candidates = [odd for odd in odds if odd.market_type == market]
    closing = [odd for odd in candidates if odd.is_closing_line]
    return closing or candidates


def _select_opening_lines(
    odds: Sequence[SportsGameOdds], market: str
) -> list[SportsGameOdds]:
    candidates = [odd for odd in odds if odd.market_type == market]
    return [odd for odd in candidates if not odd.is_closing_line]


def _implied_probability(price: float | None) -> float | None:
    if price is None or price == 0:
        return None
    if price > 0:
        return 100 / (price + 100)
    return -price / (-price + 100)


def _team_abbr(team: SportsTeam | None) -> str | None:
    """Resolve display abbreviation: abbreviation → short_name → name[:3]."""
    if team is None:
        return None
    return team.abbreviation or team.short_name or (team.name[:3].upper() if team.name else None)


def _fmt_american_odds(price: float | None) -> str | None:
    """Format American odds: +130, -110. Returns None if price is None."""
    if price is None:
        return None
    p = int(price)
    return f"+{p}" if p >= 0 else str(p)


def compute_derived_metrics(
    game: SportsGame, odds: Sequence[SportsGameOdds]
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if game.home_score is not None and game.away_score is not None:
        home = game.home_score
        away = game.away_score
        metrics["home_score"] = home
        metrics["away_score"] = away
        metrics["margin_of_victory"] = home - away
        metrics["combined_score"] = home + away
        metrics["winner"] = (
            "home" if home > away else ("away" if away > home else "tie")
        )

    # Build side-matching key sets once for reuse across spread sections
    home_keys = {
        (game.home_team.name or "").lower() if game.home_team else "",
        (game.home_team.short_name or "").lower() if game.home_team else "",
        (game.home_team.abbreviation or "").lower() if game.home_team else "",
    }
    away_keys = {
        (game.away_team.name or "").lower() if game.away_team else "",
        (game.away_team.short_name or "").lower() if game.away_team else "",
        (game.away_team.abbreviation or "").lower() if game.away_team else "",
    }

    def _matches_side(side_val: str | None, keys: set[str]) -> bool:
        if not side_val:
            return False
        s = side_val.lower()
        for k in keys:
            if not k:
                continue
            if k.startswith(s) or s.startswith(k):
                return True
        return s in {"home", "away"}

    def _extract_spread_metrics(
        lines: list[SportsGameOdds], prefix: str
    ) -> None:
        """Extract spread metrics for a given set of lines into *metrics*."""
        for line in lines:
            side = (line.side or "").lower()
            if _matches_side(side, home_keys):
                metrics[f"{prefix}_spread_home"] = line.line
                metrics[f"{prefix}_spread_home_price"] = line.price
            elif _matches_side(side, away_keys):
                metrics[f"{prefix}_spread_away"] = line.line
                metrics[f"{prefix}_spread_away_price"] = line.price

        if f"{prefix}_spread_home" not in metrics and f"{prefix}_spread_away" in metrics:
            away_line = metrics[f"{prefix}_spread_away"]
            if away_line is not None:
                metrics[f"{prefix}_spread_home"] = -(away_line)
        if f"{prefix}_spread_away" not in metrics and f"{prefix}_spread_home" in metrics:
            home_line = metrics[f"{prefix}_spread_home"]
            if home_line is not None:
                metrics[f"{prefix}_spread_away"] = -(home_line)

    # --- Spread: closing ---
    spread_lines = _select_closing_lines(odds, "spread")
    if spread_lines:
        _extract_spread_metrics(spread_lines, "closing")

        if game.home_score is not None and game.away_score is not None:
            if "closing_spread_home" in metrics:
                cover = metrics["margin_of_victory"] - (metrics["closing_spread_home"] or 0)
                metrics["did_home_cover"] = cover > 0
                metrics["did_away_cover"] = cover < 0

    # --- Spread: opening ---
    opening_spread_lines = _select_opening_lines(odds, "spread")
    if opening_spread_lines:
        _extract_spread_metrics(opening_spread_lines, "opening")

    # --- Spread: line movement ---
    if "opening_spread_home" in metrics and "closing_spread_home" in metrics:
        opening_val = metrics["opening_spread_home"] or 0
        closing_val = metrics["closing_spread_home"] or 0
        metrics["line_movement_spread"] = closing_val - opening_val

    # --- Total: closing ---
    total_lines = _select_closing_lines(odds, "total")
    if total_lines:
        total_line = total_lines[0]
        metrics["closing_total"] = total_line.line or 0
        metrics["closing_total_price"] = total_line.price
        if "combined_score" in metrics:
            total_value = metrics["closing_total"]
            combined = metrics["combined_score"]
            metrics["total_result"] = (
                "over"
                if combined > total_value
                else "under"
                if combined < total_value
                else "push"
            )

    # --- Total: opening ---
    opening_total_lines = _select_opening_lines(odds, "total")
    if opening_total_lines:
        opening_total_line = opening_total_lines[0]
        metrics["opening_total"] = opening_total_line.line
        metrics["opening_total_price"] = opening_total_line.price

    # --- Total: line movement ---
    if "opening_total" in metrics and "closing_total" in metrics:
        opening_t = metrics["opening_total"] or 0
        closing_t = metrics["closing_total"] or 0
        metrics["line_movement_total"] = closing_t - opening_t

    # --- Moneyline: closing ---
    moneyline = _select_closing_lines(odds, "moneyline")
    if moneyline:
        for line in moneyline:
            if line.side is None:
                continue
            side = line.side.lower()
            prob = _implied_probability(line.price)
            if side in {"home", game.home_team.name.lower() if game.home_team else ""}:
                metrics["closing_ml_home"] = line.price
                metrics["closing_ml_home_implied"] = prob
            if side in {"away", game.away_team.name.lower() if game.away_team else ""}:
                metrics["closing_ml_away"] = line.price
                metrics["closing_ml_away_implied"] = prob
        if "winner" in metrics:
            if (
                metrics["winner"] == "home"
                and "closing_ml_home" in metrics
                and "closing_ml_away" in metrics
            ):
                metrics["moneyline_upset"] = (metrics["closing_ml_home"] or 0) > (
                    metrics["closing_ml_away"] or 0
                )
            elif (
                metrics["winner"] == "away"
                and "closing_ml_home" in metrics
                and "closing_ml_away" in metrics
            ):
                metrics["moneyline_upset"] = (metrics["closing_ml_away"] or 0) > (
                    metrics["closing_ml_home"] or 0
                )

    # --- Moneyline: opening ---
    opening_ml = _select_opening_lines(odds, "moneyline")
    if opening_ml:
        for line in opening_ml:
            if line.side is None:
                continue
            side = line.side.lower()
            prob = _implied_probability(line.price)
            if side in {"home", game.home_team.name.lower() if game.home_team else ""}:
                metrics["opening_ml_home"] = line.price
                metrics["opening_ml_home_implied"] = prob
            if side in {"away", game.away_team.name.lower() if game.away_team else ""}:
                metrics["opening_ml_away"] = line.price
                metrics["opening_ml_away_implied"] = prob

    # --- Display labels ---
    home_abbr = _team_abbr(game.home_team)
    away_abbr = _team_abbr(game.away_team)

    # Pregame spread label — e.g. "BOS -3.5 (-110)"
    if "closing_spread_home" in metrics and home_abbr:
        spread_val = metrics["closing_spread_home"]
        if spread_val is not None:
            sign = "+" if spread_val > 0 else ""
            lbl = f"{home_abbr} {sign}{spread_val}"
            price_str = _fmt_american_odds(metrics.get("closing_spread_home_price"))
            if price_str:
                lbl += f" ({price_str})"
            metrics["pregame_spread_label"] = lbl

    # Pregame total label — e.g. "O/U 215.5 (-110)"
    if "closing_total" in metrics:
        total_val = metrics["closing_total"]
        lbl = f"O/U {total_val}"
        price_str = _fmt_american_odds(metrics.get("closing_total_price"))
        if price_str:
            lbl += f" ({price_str})"
        metrics["pregame_total_label"] = lbl

    # Pregame moneyline labels — e.g. "BOS -150", "NYK +130"
    if "closing_ml_home" in metrics and home_abbr:
        odds_str = _fmt_american_odds(metrics["closing_ml_home"])
        if odds_str:
            metrics["pregame_ml_home_label"] = f"{home_abbr} {odds_str}"
    if "closing_ml_away" in metrics and away_abbr:
        odds_str = _fmt_american_odds(metrics["closing_ml_away"])
        if odds_str:
            metrics["pregame_ml_away_label"] = f"{away_abbr} {odds_str}"

    # Outcome labels (only for completed games with scores)
    if game.home_score is not None and game.away_score is not None:
        # Spread outcome — e.g. "BOS covered by 3.5" or "Push"
        if "closing_spread_home" in metrics and "margin_of_victory" in metrics:
            ats_margin = metrics["margin_of_victory"] + (metrics["closing_spread_home"] or 0)
            if ats_margin == 0:
                metrics["spread_outcome_label"] = "Push"
            elif home_abbr and away_abbr:
                coverer = home_abbr if ats_margin > 0 else away_abbr
                metrics["spread_outcome_label"] = f"{coverer} covered by {round(abs(ats_margin), 1)}"

        # Total outcome — e.g. "Over by 7" or "Push"
        if "closing_total" in metrics and "combined_score" in metrics:
            diff = metrics["combined_score"] - metrics["closing_total"]
            if diff == 0:
                metrics["total_outcome_label"] = "Push"
            elif diff > 0:
                metrics["total_outcome_label"] = f"Over by {round(abs(diff), 1)}"
            else:
                metrics["total_outcome_label"] = f"Under by {round(abs(diff), 1)}"

        # ML outcome — e.g. "NYK upset (+130)" or "BOS won (-150)"
        winner = metrics.get("winner")
        if winner in ("home", "away") and home_abbr and away_abbr:
            win_abbr = home_abbr if winner == "home" else away_abbr
            win_ml_key = f"closing_ml_{winner}"
            win_price = metrics.get(win_ml_key)
            is_upset = metrics.get("moneyline_upset", False)
            odds_str = _fmt_american_odds(win_price)
            lbl = f"{win_abbr} upset" if is_upset else f"{win_abbr} won"
            if odds_str:
                lbl += f" ({odds_str})"
            metrics["ml_outcome_label"] = lbl

    return metrics
