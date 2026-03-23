"""DataGolf API client.

Wraps the DataGolf feeds API (https://feeds.datagolf.com/) with
rate limiting, structured logging, and typed response parsing.

Authentication is via API key passed as a ``key`` query parameter.
Rate limit: 45 requests/minute with 5-minute suspension on violation.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import httpx

from .models import (
    DGDFSProjection,
    DGEventResult,
    DGFieldEntry,
    DGLeaderboardEntry,
    DGMatchup,
    DGOddsOutright,
    DGPlayer,
    DGPreTournamentPred,
    DGRanking,
    DGRound,
    DGSkillRating,
    DGTournament,
)

_BASE_URL = "https://feeds.datagolf.com"

# 45 req/min = 0.75 req/sec.  Minimum interval between requests.
_MIN_REQUEST_INTERVAL = 1.4  # seconds (~43 req/min, under the 45 limit)

# Use the scraper's structured logger (supports keyword args like
# logger.warning("msg", key=val)).  Imported lazily at first use to
# avoid circular imports during test collection.
_logger = None


def _log():
    global _logger
    if _logger is None:
        try:
            from ..logging import logger as _l
            _logger = _l
        except Exception:
            import logging
            _logger = logging.getLogger(__name__)
    return _logger


class DataGolfClient:
    """Client for the DataGolf feeds API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or ""
        if not self._api_key:
            # Try loading from settings at runtime (not import time)
            try:
                from ..config import settings
                self._api_key = getattr(settings, "datagolf_api_key", "") or ""
            except Exception:
                pass
        self._client = httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "sports-data-admin/1.0"},
        )
        self._last_request_at = 0.0

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make an authenticated GET request to DataGolf."""
        url = f"{_BASE_URL}{path}"
        all_params = {"key": self._api_key, "file_format": "json"}
        if params:
            all_params.update(params)

        # Simple rate limiting
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        try:
            resp = self._client.get(url, params=all_params)
            self._last_request_at = time.monotonic()
        except Exception as exc:
            _log().warning("datagolf_request_failed", path=path, error=str(exc))
            return None

        if resp.status_code != 200:
            _log().warning(
                "datagolf_api_error",
                path=path,
                status=resp.status_code,
                body=resp.text[:200] if resp.text else "",
            )
            return None

        return resp.json()

    # ------------------------------------------------------------------
    # General endpoints
    # ------------------------------------------------------------------

    def get_schedule(self, tour: str = "pga", season: int | None = None) -> list[DGTournament]:
        """Fetch tour schedule."""
        params: dict[str, Any] = {"tour": tour}
        if season:
            params["season"] = season

        data = self._get("/get-schedule", params)
        if not data:
            return []

        schedule = data if isinstance(data, list) else data.get("schedule", [])
        tournaments = []
        for evt in schedule:
            try:
                from datetime import timedelta

                start = _parse_date(evt.get("start_date", evt.get("date", "")))
                end = _parse_date(evt.get("end_date"))
                # DataGolf doesn't return end_date; estimate as start + 3 days
                # (standard PGA event: Thu–Sun)
                if end is None and start is not None:
                    end = start + timedelta(days=3)

                # Map DataGolf status to our convention
                dg_status = evt.get("status", "")
                status = _map_tournament_status(dg_status)

                tournaments.append(DGTournament(
                    event_id=str(evt.get("event_id", "")),
                    event_name=evt.get("event_name", ""),
                    course=evt.get("course", ""),
                    course_key=evt.get("course_key", evt.get("course", "")),
                    start_date=start,
                    end_date=end,
                    tour=tour,
                    status=status,
                    purse=_safe_float(evt.get("purse")),
                    latitude=_safe_float(evt.get("latitude")),
                    longitude=_safe_float(evt.get("longitude")),
                    country=evt.get("country"),
                    season=season,
                ))
            except Exception as exc:
                _log().warning("datagolf_schedule_parse_error", event=evt, error=str(exc))
        return tournaments

    def get_player_list(self) -> list[DGPlayer]:
        """Fetch full player catalog."""
        data = self._get("/get-player-list")
        if not data:
            return []

        players = []
        for p in data:
            try:
                players.append(DGPlayer(
                    dg_id=int(p.get("dg_id", 0)),
                    player_name=p.get("player_name", ""),
                    country=p.get("country"),
                    country_code=p.get("country_code"),
                    amateur=bool(p.get("amateur", False)),
                    dk_id=_safe_int(p.get("dk_id")),
                    fd_id=_safe_int(p.get("fd_id")),
                    yahoo_id=_safe_int(p.get("yahoo_id")),
                ))
            except Exception as exc:
                _log().warning("datagolf_player_parse_error", player=p, error=str(exc))
        return players

    def get_field_updates(self, tour: str = "pga") -> list[DGFieldEntry]:
        """Fetch current tournament field and tee times."""
        data = self._get("/field-updates", {"tour": tour})
        if not data:
            return []

        field_data = data.get("field", data) if isinstance(data, dict) else data
        if not isinstance(field_data, list):
            field_data = []

        entries = []
        for f in field_data:
            try:
                entries.append(DGFieldEntry(
                    dg_id=int(f.get("dg_id", 0)),
                    player_name=f.get("player_name", ""),
                    country=f.get("country"),
                    dk_salary=_safe_int(f.get("dk_salary")),
                    fd_salary=_safe_int(f.get("fd_salary")),
                    early_late=f.get("early_late"),
                    tee_time=f.get("tee_time"),
                    course=f.get("course"),
                    r1_teetime=f.get("r1_teetime"),
                    r2_teetime=f.get("r2_teetime"),
                ))
            except Exception as exc:
                _log().warning("datagolf_field_parse_error", entry=f, error=str(exc))
        return entries

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------

    def get_skill_ratings(self, tour: str = "pga") -> list[DGSkillRating]:
        """Fetch player skill ratings (SG components)."""
        data = self._get("/preds/skill-ratings", {"display": "value", "tour": tour})
        if not data:
            return []

        players = data.get("players", data) if isinstance(data, dict) else data
        if not isinstance(players, list):
            return []

        ratings = []
        for p in players:
            try:
                ratings.append(DGSkillRating(
                    dg_id=int(p.get("dg_id", 0)),
                    player_name=p.get("player_name", ""),
                    sg_total=_safe_float(p.get("sg_total")),
                    sg_ott=_safe_float(p.get("sg_ott")),
                    sg_app=_safe_float(p.get("sg_app")),
                    sg_arg=_safe_float(p.get("sg_arg")),
                    sg_putt=_safe_float(p.get("sg_putt")),
                    driving_dist=_safe_float(p.get("driving_dist")),
                    driving_acc=_safe_float(p.get("driving_acc")),
                    sample_size=_safe_int(p.get("sample_size")),
                ))
            except Exception as exc:
                _log().warning("datagolf_skill_parse_error", player=p, error=str(exc))
        return ratings

    def get_rankings(self) -> list[DGRanking]:
        """Fetch DataGolf top-500 rankings."""
        data = self._get("/preds/get-dg-rankings")
        if not data:
            return []

        rankings_data = data.get("rankings", data) if isinstance(data, dict) else data
        if not isinstance(rankings_data, list):
            return []

        rankings = []
        for r in rankings_data:
            try:
                rankings.append(DGRanking(
                    dg_id=int(r.get("dg_id", 0)),
                    player_name=r.get("player_name", ""),
                    rank=int(r.get("rank", 0)),
                    datagolf_rank=_safe_int(r.get("datagolf_rank")),
                    owgr=_safe_int(r.get("owgr")),
                    am=bool(r.get("am", False)),
                ))
            except Exception as exc:
                _log().warning("datagolf_ranking_parse_error", entry=r, error=str(exc))
        return rankings

    def get_pre_tournament_predictions(
        self, tour: str = "pga",
    ) -> list[DGPreTournamentPred]:
        """Fetch pre-tournament win/top5/top10/MC probabilities."""
        data = self._get("/preds/pre-tournament", {"tour": tour, "odds_format": "percent"})
        if not data:
            return []

        baseline = data.get("baseline_history_fit", data) if isinstance(data, dict) else data
        if not isinstance(baseline, list):
            return []

        preds = []
        for p in baseline:
            try:
                preds.append(DGPreTournamentPred(
                    dg_id=int(p.get("dg_id", 0)),
                    player_name=p.get("player_name", ""),
                    win_prob=_safe_float(p.get("win_prob")),
                    top_5_prob=_safe_float(p.get("top_5")),
                    top_10_prob=_safe_float(p.get("top_10")),
                    top_20_prob=_safe_float(p.get("top_20")),
                    make_cut_prob=_safe_float(p.get("make_cut")),
                ))
            except Exception as exc:
                _log().warning("datagolf_pred_parse_error", player=p, error=str(exc))
        return preds

    def get_live_predictions(self) -> list[DGLeaderboardEntry]:
        """Fetch live in-play predictions and leaderboard."""
        data = self._get("/preds/in-play", {"odds_format": "percent"})
        if not data:
            return []

        players = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(players, list):
            return []

        return [self._parse_leaderboard_entry(p) for p in players if p]

    def get_live_tournament_stats(self) -> list[DGLeaderboardEntry]:
        """Fetch live tournament stats (SG + traditional stats per player)."""
        data = self._get("/preds/live-tournament-stats")
        if not data:
            return []

        live_stats = data.get("live_stats", data) if isinstance(data, dict) else data
        if not isinstance(live_stats, list):
            return []

        return [self._parse_leaderboard_entry(p) for p in live_stats if p]

    # ------------------------------------------------------------------
    # Odds
    # ------------------------------------------------------------------

    def get_outrights(
        self,
        tour: str = "pga",
        market: str = "win",
        odds_format: str = "american",
    ) -> list[DGOddsOutright]:
        """Fetch outright odds (win, top 5, top 10, make cut)."""
        data = self._get("/betting-tools/outrights", {
            "tour": tour,
            "market": market,
            "odds_format": odds_format,
        })
        if not data:
            return []

        odds_data = data.get("odds", data) if isinstance(data, dict) else data
        if not isinstance(odds_data, list):
            return []

        all_odds: list[DGOddsOutright] = []
        for player_odds in odds_data:
            dg_id = int(player_odds.get("dg_id", 0))
            player_name = player_odds.get("player_name", "")
            dg_prob = _safe_float(player_odds.get("datagolf"))

            # Each player entry has odds per sportsbook
            for book_key in ("draftkings", "fanduel", "betmgm", "caesars",
                             "pinnacle", "bet365", "betrivers", "pointsbet",
                             "unibet", "william_hill", "espnbet"):
                odds_val = player_odds.get(book_key)
                if odds_val is not None:
                    all_odds.append(DGOddsOutright(
                        dg_id=dg_id,
                        player_name=player_name,
                        book=book_key,
                        market=market,
                        odds=float(odds_val),
                        dg_prob=dg_prob,
                    ))

        return all_odds

    def get_matchups(
        self,
        tour: str = "pga",
        odds_format: str = "american",
    ) -> list[DGMatchup]:
        """Fetch head-to-head and 3-ball matchup odds."""
        data = self._get("/betting-tools/matchups", {
            "tour": tour,
            "odds_format": odds_format,
        })
        if not data:
            return []

        matchups: list[DGMatchup] = []
        for matchup_type in ("2_balls", "3_balls"):
            type_data = data.get(matchup_type, []) if isinstance(data, dict) else []
            for m in type_data:
                book = m.get("book", "")
                players = m.get("players", [])
                matchups.append(DGMatchup(
                    matchup_type=matchup_type,
                    book=book,
                    players=players,
                ))
        return matchups

    # ------------------------------------------------------------------
    # DFS
    # ------------------------------------------------------------------

    def get_dfs_projections(
        self,
        site: str = "draftkings",
        tour: str = "pga",
    ) -> list[DGDFSProjection]:
        """Fetch DFS salary and projection defaults."""
        data = self._get("/preds/fantasy-projection-defaults", {
            "site": site,
            "tour": tour,
        })
        if not data:
            return []

        projections_data = data.get("projections", data) if isinstance(data, dict) else data
        if not isinstance(projections_data, list):
            return []

        projections = []
        for p in projections_data:
            try:
                projections.append(DGDFSProjection(
                    dg_id=int(p.get("dg_id", 0)),
                    player_name=p.get("player_name", ""),
                    site=site,
                    salary=int(p.get("salary", 0)),
                    projected_points=_safe_float(p.get("proj_pts", p.get("projected_points"))),
                    projected_ownership=_safe_float(p.get("proj_own", p.get("projected_ownership"))),
                ))
            except Exception as exc:
                _log().warning("datagolf_dfs_parse_error", player=p, error=str(exc))
        return projections

    # ------------------------------------------------------------------
    # Historical
    # ------------------------------------------------------------------

    def get_historical_rounds(
        self,
        tour: str = "pga",
        event_id: str | None = None,
        year: int | None = None,
    ) -> list[DGRound]:
        """Fetch historical round-level scoring and stats."""
        params: dict[str, Any] = {"tour": tour}
        if event_id:
            params["event_id"] = event_id
        if year:
            params["year"] = year

        data = self._get("/historical-raw-data/rounds", params)
        if not data:
            return []

        rounds_data = data if isinstance(data, list) else data.get("rounds", [])
        rounds = []
        for r in rounds_data:
            try:
                rounds.append(DGRound(
                    dg_id=int(r.get("dg_id", 0)),
                    player_name=r.get("player_name", ""),
                    event_id=str(r.get("event_id", "")),
                    round_num=int(r.get("round_num", r.get("round", 0))),
                    course=r.get("course_name", r.get("course")),
                    score=_safe_int(r.get("score")),
                    strokes=_safe_int(r.get("strokes")),
                    sg_total=_safe_float(r.get("sg_total")),
                    sg_ott=_safe_float(r.get("sg_ott")),
                    sg_app=_safe_float(r.get("sg_app")),
                    sg_arg=_safe_float(r.get("sg_arg")),
                    sg_putt=_safe_float(r.get("sg_putt")),
                    driving_dist=_safe_float(r.get("driving_dist")),
                    driving_acc=_safe_float(r.get("driving_acc")),
                    gir=_safe_float(r.get("gir")),
                    scrambling=_safe_float(r.get("scrambling")),
                    prox=_safe_float(r.get("prox")),
                    putts_per_round=_safe_float(r.get("putts_per_round")),
                ))
            except Exception as exc:
                _log().warning("datagolf_round_parse_error", round_data=r, error=str(exc))
        return rounds

    def get_historical_results(
        self,
        tour: str = "pga",
        event_id: str | None = None,
        year: int | None = None,
    ) -> list[DGEventResult]:
        """Fetch historical event finishes."""
        params: dict[str, Any] = {"tour": tour}
        if event_id:
            params["event_id"] = event_id
        if year:
            params["year"] = year

        data = self._get("/historical-event-data/events", params)
        if not data:
            return []

        results_data = data if isinstance(data, list) else data.get("results", [])
        results = []
        for r in results_data:
            try:
                results.append(DGEventResult(
                    dg_id=int(r.get("dg_id", 0)),
                    player_name=r.get("player_name", ""),
                    event_id=str(r.get("event_id", "")),
                    event_name=r.get("event_name", ""),
                    finish_position=_safe_int(r.get("fin_pos", r.get("finish_position"))),
                    score=_safe_int(r.get("score")),
                    earnings=_safe_float(r.get("earnings")),
                    fedex_pts=_safe_float(r.get("fedex_pts")),
                    season=_safe_int(r.get("season", r.get("year"))),
                ))
            except Exception as exc:
                _log().warning("datagolf_result_parse_error", result=r, error=str(exc))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_leaderboard_entry(self, p: dict) -> DGLeaderboardEntry:
        # Position: in-play uses "current_pos" (e.g. "T4"), stats uses "position"
        pos_raw = p.get("current_pos") or p.get("position") or p.get("pos")
        position = _safe_int(str(pos_raw).lstrip("T")) if pos_raw else None

        # Score: in-play uses "current_score", stats uses "total"
        total_score = _safe_int(p.get("current_score")) or _safe_int(p.get("total", p.get("total_score")))

        return DGLeaderboardEntry(
            dg_id=int(p.get("dg_id", 0)),
            player_name=p.get("player_name", ""),
            position=position,
            total_score=total_score,
            today_score=_safe_int(p.get("today", p.get("today_score"))),
            thru=_safe_int(p.get("thru")),
            total_strokes=_safe_int(p.get("total_strokes")),
            r1=_safe_int(p.get("R1", p.get("r1"))),
            r2=_safe_int(p.get("R2", p.get("r2"))),
            r3=_safe_int(p.get("R3", p.get("r3"))),
            r4=_safe_int(p.get("R4", p.get("r4"))),
            sg_total=_safe_float(p.get("sg_total")),
            sg_ott=_safe_float(p.get("sg_ott")),
            sg_app=_safe_float(p.get("sg_app")),
            sg_arg=_safe_float(p.get("sg_arg")),
            sg_putt=_safe_float(p.get("sg_putt")),
            status=p.get("status", "active"),
            win_prob=_safe_float(p.get("win", p.get("win_prob"))),
            top_5_prob=_safe_float(p.get("top_5")),
            top_10_prob=_safe_float(p.get("top_10")),
            make_cut_prob=_safe_float(p.get("make_cut")),
        )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float | None:
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None or val == "" or val == "-":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _map_tournament_status(dg_status: str) -> str:
    """Map DataGolf status strings to our convention."""
    s = (dg_status or "").lower().strip()
    if s in ("completed", "complete"):
        return "completed"
    if s in ("in progress", "in_progress", "live"):
        return "in_progress"
    if s in ("canceled", "cancelled"):
        return "canceled"
    return "scheduled"


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        return None
