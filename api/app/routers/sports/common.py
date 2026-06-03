"""Shared helpers for sports admin routes."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select

from ...db import AsyncSession
from ...db.scraper import SportsScrapeRun
from ...db.sports import (
    SportsGamePlay,
    SportsLeague,
)
from ...services.nhl_context import build_nhl_play_situation, nhl_consumer_play_metadata
from .schemas import (
    PlayEntry,
    ScrapeRunConfig,
    ScrapeRunResponse,
)
from .schemas.common import _score_obj
from .stat_serializers import (
    serialize_mlb_batter as serialize_mlb_batter,
)
from .stat_serializers import (
    serialize_mlb_pitcher as serialize_mlb_pitcher,
)
from .stat_serializers import (
    serialize_nhl_goalie as serialize_nhl_goalie,
)
from .stat_serializers import (
    serialize_nhl_skater as serialize_nhl_skater,
)
from .stat_serializers import (
    serialize_player_stat as serialize_player_stat,
)
from .stat_serializers import (
    serialize_team_stat as serialize_team_stat,
)


def serialize_play_entry(play: SportsGamePlay, league_code: str | None = None) -> PlayEntry:
    """Serialize a play record to API response format."""
    from ...services.period_labels import period_label, time_label

    team_abbr = None
    period_type: str | None = None
    raw_data = play.raw_data if isinstance(play.raw_data, dict) else {}
    if play.team:
        team_abbr = play.team.abbreviation
    if raw_data:
        if team_abbr is None:
            team_abbr = raw_data.get("team_abbreviation")
        # Source-supplied period type (NHL: "REG"/"OT"/"SO") — used to
        # disambiguate shootouts from overtime when labeling.
        raw_ptype = raw_data.get("period_type")
        if isinstance(raw_ptype, str) and raw_ptype:
            period_type = raw_ptype

    # Compute display-ready period/time labels when league + period are available
    p_label: str | None = None
    t_label: str | None = None
    if play.quarter is not None and league_code:
        p_label = period_label(play.quarter, league_code, period_type)
        t_label = time_label(play.quarter, play.game_clock, league_code, period_type)

    situation_before, situation_after = _play_situations(
        play=play,
        raw_data=raw_data,
        league_code=league_code,
        team_abbr=team_abbr,
        period_label=p_label,
        time_label_value=t_label,
    )

    return PlayEntry(
        play_index=play.play_index,
        quarter=play.quarter,
        game_clock=play.game_clock,
        period_label=p_label,
        time_label=t_label,
        period_type=period_type,
        play_type=play.play_type,
        team_abbreviation=team_abbr,
        player_name=play.player_name,
        description=play.description,
        score=_score_obj(play.home_score, play.away_score),
        situation_before=situation_before,
        situation_after=situation_after,
        sport_metadata=_sport_metadata(play=play, raw_data=raw_data, league_code=league_code),
        metadata=_consumer_play_metadata(raw_data),
        raw_feed_text=_raw_feed_text(play=play, raw_data=raw_data),
        raw_feed_source="upstream" if raw_data else None,
    )


def _play_situations(
    *,
    play: SportsGamePlay,
    raw_data: dict[str, Any],
    league_code: str | None,
    team_abbr: str | None,
    period_label: str | None,
    time_label_value: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    code = (league_code or "").upper()
    if not raw_data:
        return None, None

    if code == "NHL":
        before = build_nhl_play_situation(
            raw_data=raw_data,
            period_ordinal=play.quarter,
            period_label=period_label,
            clock_label=time_label_value or play.game_clock,
            team_abbr=team_abbr,
            player_name=play.player_name,
            play_type=play.play_type,
        )
        return before, None

    if code != "MLB":
        return None, None

    before = _mlb_situation(
        play=play,
        raw_data=raw_data,
        team_abbr=team_abbr,
        period_label=period_label,
        time_label_value=time_label_value,
        suffix="Before",
    )
    after = _mlb_situation(
        play=play,
        raw_data=raw_data,
        team_abbr=team_abbr,
        period_label=period_label,
        time_label_value=time_label_value,
        suffix="After",
    )
    return before, after


def _mlb_situation(
    *,
    play: SportsGamePlay,
    raw_data: dict[str, Any],
    team_abbr: str | None,
    period_label: str | None,
    time_label_value: str | None,
    suffix: str,
) -> dict[str, Any] | None:
    from ...scroll_down_mlb._state_readers import (
        inning_half_from_upstream,
        read_base_state_after,
        read_base_state_before,
        read_count,
        read_count_before,
        read_num,
        read_str,
    )

    is_before = suffix == "Before"
    snapshot = raw_data.get(f"situation{suffix}")
    if not isinstance(snapshot, dict):
        snapshot = {}
    bases = (
        read_base_state_before(raw_data)
        if is_before
        else read_base_state_after(raw_data)
    ) or _situation_base_state(snapshot)
    count = (
        read_count_before(raw_data)
        if is_before
        else read_count(raw_data)
    ) or _situation_count(snapshot)
    inning = read_num(
        snapshot.get("inning"),
        raw_data.get(f"inning{suffix}"),
        raw_data.get("inning"),
        raw_data.get("period"),
        play.quarter,
    )
    half = (
        read_str(
            snapshot.get("half"),
            raw_data.get(f"half{suffix}"),
            raw_data.get("half"),
            raw_data.get("inningHalf"),
            raw_data.get("halfInning"),
        )
        or inning_half_from_upstream(raw_data, None)
    )
    outs = read_num(
        snapshot.get("outs"),
        raw_data.get(f"outs{suffix}"),
        raw_data.get("outsBefore" if is_before else "outsAfter"),
    )
    if outs is None and is_before:
        outs = read_num(raw_data.get("outs"))

    batter_name = read_str(
        raw_data.get("batterName"),
        snapshot.get("batterName"),
        (raw_data.get("batter") or {}).get("name") if isinstance(raw_data.get("batter"), dict) else None,
        play.player_name,
    )
    pitcher_name = read_str(
        raw_data.get("pitcherName"),
        snapshot.get("pitcherName"),
        (raw_data.get("pitcher") or {}).get("name") if isinstance(raw_data.get("pitcher"), dict) else None,
    )
    batting_team = read_str(
        raw_data.get("battingTeamAbbreviation"),
        raw_data.get("battingTeamAbbr"),
        raw_data.get("teamAbbreviation"),
        raw_data.get("team_abbreviation"),
        team_abbr,
    )

    if not any([inning, half, bases, count, outs is not None, batter_name, pitcher_name, batting_team]):
        return None

    baseball = {
        "inning": inning,
        "half": half,
        "outs": outs,
        "bases": bases,
        "baseState": _base_state_label(bases),
        "battingTeamAbbreviation": batting_team,
        "fieldingTeamAbbreviation": read_str(
            raw_data.get("fieldingTeamAbbreviation"),
            raw_data.get("fieldingTeamAbbr"),
        ),
        "batterName": batter_name,
        "pitcherName": pitcher_name,
    }
    if count:
        baseball["balls"], baseball["strikes"] = count

    return _drop_none(
        {
            "schemaVersion": 1,
            "sport": "mlb",
            "display": _drop_none(
                {
                    "headline": _mlb_situation_headline(half=half, inning=inning, outs=outs, bases=bases),
                    "subheadline": _mlb_count_text(count),
                }
            ),
            "period": _drop_none({"ordinal": inning, "label": period_label, "phase": half}),
            "clock": _drop_none({"label": time_label_value}),
            "possession": _drop_none({"teamAbbreviation": batting_team}),
            "sportState": {"baseball": _drop_none(baseball)},
            "confidence": {"level": "medium", "source": "upstream"},
        }
    )


def _situation_base_state(snapshot: dict[str, Any]) -> dict[str, bool] | None:
    raw = snapshot.get("bases") or snapshot.get("baseState")
    if not isinstance(raw, dict):
        return None
    return {
        "first": bool(raw.get("first")),
        "second": bool(raw.get("second")),
        "third": bool(raw.get("third")),
    }


def _situation_count(snapshot: dict[str, Any]) -> tuple[int, int] | None:
    count = snapshot.get("count")
    if not isinstance(count, dict):
        return None
    balls = count.get("balls")
    strikes = count.get("strikes")
    if (
        isinstance(balls, int | float)
        and not isinstance(balls, bool)
        and isinstance(strikes, int | float)
        and not isinstance(strikes, bool)
    ):
        return int(balls), int(strikes)
    return None


def _base_state_label(bases: dict[str, bool] | None) -> str | None:
    if not bases:
        return None
    occupied = [label for key, label in [("first", "1st"), ("second", "2nd"), ("third", "3rd")] if bases.get(key)]
    return ", ".join(occupied) if occupied else "Bases empty"


def _mlb_count_text(count: tuple[int, int] | None) -> str | None:
    if not count:
        return None
    return f"{count[0]}-{count[1]} count"


def _mlb_situation_headline(
    *,
    half: str | None,
    inning: int | None,
    outs: int | None,
    bases: dict[str, bool] | None,
) -> str | None:
    pieces = []
    if half and inning:
        pieces.append(f"{half.title()} {inning}")
    if outs is not None:
        pieces.append("0 out" if outs == 0 else "1 out" if outs == 1 else f"{outs} outs")
    if bases:
        pieces.append(_base_state_label(bases) or "")
    return ", ".join(piece for piece in pieces if piece)


def _sport_metadata(
    *, play: SportsGamePlay, raw_data: dict[str, Any], league_code: str | None
) -> dict[str, Any] | None:
    metadata = _consumer_play_metadata(raw_data) or {}
    metadata["playIndex"] = play.play_index
    if league_code:
        metadata["sport"] = league_code.lower()
    return metadata


def _consumer_play_metadata(raw_data: dict[str, Any]) -> dict[str, Any] | None:
    if not raw_data:
        return None
    allowed_keys = [
        "eventType",
        "event_type",
        "result",
        "isScoringPlay",
        "winProbability",
        "winProbabilityDelta",
    ]
    values = {key: raw_data[key] for key in allowed_keys if key in raw_data}
    if "situation_code" in raw_data or "type_desc_key" in raw_data:
        values.update(nhl_consumer_play_metadata(raw_data) or {})
    return values or None


def _raw_feed_text(*, play: SportsGamePlay, raw_data: dict[str, Any]) -> str | None:
    for value in (
        raw_data.get("description"),
        raw_data.get("rawDescription"),
        raw_data.get("playDescription"),
        play.description,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _drop_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: nested for key, nested in value.items() if nested is not None and nested != {}}


_URL_PATTERN = re.compile(r"https?://\S+")


def normalize_post_text(text: str | None) -> str | None:
    """Normalize post text for deduplication."""
    if not text:
        return None
    cleaned = _URL_PATTERN.sub("", text.lower())
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


async def get_league(session: AsyncSession, code: str) -> SportsLeague:
    """Fetch league by code or raise 404."""
    stmt = select(SportsLeague).where(SportsLeague.code == code.upper())
    result = await session.execute(stmt)
    league = result.scalar_one_or_none()
    if not league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"League {code} not found"
        )
    return league


logger = logging.getLogger(__name__)


def _normalize_config(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Parse raw JSONB config through ScrapeRunConfig for consistent camelCase."""
    if not raw:
        return raw
    try:
        return ScrapeRunConfig(**raw).model_dump(by_alias=True)
    except ValidationError:
        logger.warning("malformed_scrape_run_config", extra={"raw_config": raw})
        return raw


def serialize_run(run: SportsScrapeRun, league_code: str) -> ScrapeRunResponse:
    """Serialize scrape run to API response."""
    return ScrapeRunResponse(
        id=run.id,
        league_code=league_code,
        status=run.status,
        scraper_type=run.scraper_type,
        job_id=run.job_id,
        season=run.season,
        start_date=run.start_date.date() if run.start_date else None,
        end_date=run.end_date.date() if run.end_date else None,
        summary=run.summary,
        error_details=run.error_details,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        requested_by=run.requested_by,
        config=_normalize_config(run.config),
    )

