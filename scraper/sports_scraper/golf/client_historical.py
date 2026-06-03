"""Historical DataGolf endpoint methods."""

from __future__ import annotations

from typing import Any

from ..logging import logger
from .client_parsing import _safe_float, _safe_int
from .models import DGEventResult, DGRound


class DataGolfHistoricalMixin:
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
                logger.warning("datagolf_round_parse_error", round_data=r, error=str(exc))
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
                logger.warning("datagolf_result_parse_error", result=r, error=str(exc))
        return results
