"""Celery task: daily pipeline coverage report.

Computes, for a given calendar day, how many FINAL games existed per sport,
how many have flows, and how many used the FALLBACK template path.  Writes
one ``PipelineCoverageReport`` row per day; re-running for the same date
overwrites the existing row (idempotent).

Default schedule: 06:00 UTC daily (added to scraper beat_schedule, routed to
the API worker's "celery" queue so it runs inside the FastAPI process tree
where the ORM models live).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from app.celery_app import celery_app
from app.tasks._task_infra import _task_db

logger = logging.getLogger(__name__)

# Stage name as stored in GamePipelineStage.stage
_VALIDATE_BLOCKS_STAGE = "VALIDATE_BLOCKS"


@celery_app.task(name="generate_pipeline_coverage_report", bind=True, max_retries=0)
def generate_pipeline_coverage_report(self, report_date_str: str | None = None) -> dict:
    """Write a PipelineCoverageReport for ``report_date_str`` (ISO date, default: yesterday)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_coverage_report(report_date_str))
    finally:
        loop.close()


async def _run_coverage_report(report_date_str: str | None) -> dict:
    """Compute and upsert the coverage report for the given date."""
    from sqlalchemy import and_, select

    import app.db.flow  # noqa: F401 — resolve SportsGame relationships
    import app.db.mlb_advanced  # noqa: F401
    import app.db.nba_advanced  # noqa: F401
    import app.db.ncaab_advanced  # noqa: F401
    import app.db.nfl_advanced  # noqa: F401
    import app.db.nhl_advanced  # noqa: F401
    import app.db.odds  # noqa: F401
    import app.db.social  # noqa: F401
    from app.db.flow import SportsGameFlow
    from app.db.pipeline import (
        GamePipelineRun,
        GamePipelineStage,
        PipelineCoverageReport,
        PipelineCoverageReportEntry,
    )
    from app.db.sports import SportsGame, SportsLeague

    if report_date_str:
        report_date = date.fromisoformat(report_date_str)
    else:
        report_date = date.today() - timedelta(days=1)

    day_start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    logger.info("coverage_report_start", extra={"report_date": str(report_date)})

    async with _task_db() as sf:
        async with sf() as db:
            # ── 1. FINAL/archived games for the target day ────────────────────
            games_stmt = (
                select(SportsGame.id, SportsLeague.code)
                .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
                .where(
                    SportsGame.status.in_(["final", "archived"]),
                    SportsGame.game_date >= day_start,
                    SportsGame.game_date < day_end,
                )
            )
            games_rows = (await db.execute(games_stmt)).all()
            game_ids = [r.id for r in games_rows]
            sport_by_game: dict[int, str] = {r.id: r.code for r in games_rows}

            # ── 2. Games that have a flow ──────────────────────────────────────
            flow_game_ids: set[int] = set()
            if game_ids:
                flows_stmt = select(SportsGameFlow.game_id).where(
                    SportsGameFlow.game_id.in_(game_ids)
                )
                flow_game_ids = {r.game_id for r in (await db.execute(flows_stmt)).all()}

            # ── 3. Determine VALIDATE_BLOCKS decision for each game with a flow
            # Pick the latest completed run per game, then look at its VALIDATE_BLOCKS stage.
            decision_by_game: dict[int, str] = {}
            if flow_game_ids:
                runs_stmt = select(GamePipelineRun.id, GamePipelineRun.game_id).where(
                    GamePipelineRun.game_id.in_(flow_game_ids),
                    GamePipelineRun.status == "completed",
                )
                runs_rows = (await db.execute(runs_stmt)).all()

                # Latest run id per game (higher id = more recent)
                latest_run_by_game: dict[int, int] = {}
                for r in runs_rows:
                    if r.game_id not in latest_run_by_game or r.id > latest_run_by_game[r.game_id]:
                        latest_run_by_game[r.game_id] = r.id

                if latest_run_by_game:
                    run_id_to_game = {v: k for k, v in latest_run_by_game.items()}
                    stages_stmt = select(
                        GamePipelineStage.run_id,
                        GamePipelineStage.output_json,
                    ).where(
                        GamePipelineStage.run_id.in_(list(latest_run_by_game.values())),
                        GamePipelineStage.stage == _VALIDATE_BLOCKS_STAGE,
                        GamePipelineStage.status == "success",
                    )
                    for row in (await db.execute(stages_stmt)).all():
                        game_id = run_id_to_game.get(row.run_id)
                        if game_id and row.output_json:
                            decision = row.output_json.get("decision")
                            if decision:
                                decision_by_game[game_id] = decision

            # ── 4. Aggregate per sport ─────────────────────────────────────────
            sports: dict[str, dict[str, int | list[float]]] = {}
            for gid, sport in sport_by_game.items():
                if sport not in sports:
                    sports[sport] = {
                        "finals_count": 0,
                        "flows_count": 0,
                        "missing_count": 0,
                        "fallback_count": 0,
                        "_quality_scores": [],
                    }
                s = sports[sport]
                s["finals_count"] += 1  # type: ignore[operator]
                if gid in flow_game_ids:
                    s["flows_count"] += 1  # type: ignore[operator]
                    decision = decision_by_game.get(gid)
                    if decision == "FALLBACK":
                        s["fallback_count"] += 1  # type: ignore[operator]
                        s["_quality_scores"].append(0.0)  # type: ignore[union-attr]
                    elif decision == "PUBLISH":
                        s["_quality_scores"].append(100.0)  # type: ignore[union-attr]
                    # REGENERATE that eventually led to a flow counts as PUBLISH quality
                else:
                    s["missing_count"] += 1  # type: ignore[operator]

            sport_breakdown = []
            for sport, s in sorted(sports.items()):
                scores: list[float] = s["_quality_scores"]  # type: ignore[assignment]
                avg_q = round(sum(scores) / len(scores), 1) if scores else None
                sport_breakdown.append(
                    {
                        "sport": sport,
                        "finals_count": s["finals_count"],
                        "flows_count": s["flows_count"],
                        "missing_count": s["missing_count"],
                        "fallback_count": s["fallback_count"],
                        "avg_quality_score": avg_q,
                    }
                )

            total_finals = sum(s["finals_count"] for s in sports.values())  # type: ignore[arg-type]
            total_flows = sum(s["flows_count"] for s in sports.values())  # type: ignore[arg-type]
            total_missing = sum(s["missing_count"] for s in sports.values())  # type: ignore[arg-type]
            total_fallbacks = sum(s["fallback_count"] for s in sports.values())  # type: ignore[arg-type]
            all_scores: list[float] = [
                q for s in sports.values() for q in s["_quality_scores"]  # type: ignore[union-attr]
            ]
            overall_avg_q = round(sum(all_scores) / len(all_scores), 1) if all_scores else None

            now = datetime.now(UTC)

            # ── 5. Upsert (idempotent: overwrite same-day row) ────────────────
            existing_stmt = select(PipelineCoverageReport).where(
                PipelineCoverageReport.report_date == report_date
            )
            existing = (await db.execute(existing_stmt)).scalar_one_or_none()

            if existing:
                existing.generated_at = now
                existing.sport_breakdown = sport_breakdown
                existing.total_finals = total_finals
                existing.total_flows = total_flows
                existing.total_missing = total_missing
                existing.total_fallbacks = total_fallbacks
                existing.avg_quality_score = overall_avg_q
            else:
                db.add(
                    PipelineCoverageReport(
                        report_date=report_date,
                        generated_at=now,
                        sport_breakdown=sport_breakdown,
                        total_finals=total_finals,
                        total_flows=total_flows,
                        total_missing=total_missing,
                        total_fallbacks=total_fallbacks,
                        avg_quality_score=overall_avg_q,
                    )
                )

            # ── 6. Upsert per-game entries ─────────────────────────────────────
            existing_entries_stmt = select(
                PipelineCoverageReportEntry.game_id
            ).where(PipelineCoverageReportEntry.report_date == report_date)
            existing_game_ids: set[int] = {
                r.game_id
                for r in (await db.execute(existing_entries_stmt)).all()
            }

            for gid, sport in sport_by_game.items():
                has_flow = gid in flow_game_ids
                gap_reason: str | None = None
                if not has_flow:
                    # Determine why: check if a pipeline run exists at all
                    any_run_stmt = select(GamePipelineRun.id).where(
                        GamePipelineRun.game_id == gid
                    ).limit(1)
                    run_row = (await db.execute(any_run_stmt)).first()
                    gap_reason = "pipeline_failed" if run_row else "no_pipeline_run"

                if gid in existing_game_ids:
                    update_stmt = (
                        select(PipelineCoverageReportEntry)
                        .where(
                            PipelineCoverageReportEntry.report_date == report_date,
                            PipelineCoverageReportEntry.game_id == gid,
                        )
                    )
                    entry = (await db.execute(update_stmt)).scalar_one_or_none()
                    if entry:
                        entry.has_flow = has_flow
                        entry.gap_reason = gap_reason
                else:
                    db.add(
                        PipelineCoverageReportEntry(
                            report_date=report_date,
                            sport=sport,
                            game_id=gid,
                            has_flow=has_flow,
                            gap_reason=gap_reason,
                        )
                    )

            await db.commit()

    logger.info(
        "coverage_report_done",
        extra={
            "report_date": str(report_date),
            "total_finals": total_finals,
            "total_flows": total_flows,
            "total_missing": total_missing,
            "total_fallbacks": total_fallbacks,
        },
    )
    return {
        "report_date": str(report_date),
        "total_finals": total_finals,
        "total_flows": total_flows,
        "total_missing": total_missing,
        "total_fallbacks": total_fallbacks,
        "avg_quality_score": overall_avg_q,
        "sport_breakdown": sport_breakdown,
    }
