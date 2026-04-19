"""Scraper-related Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class ScrapeRunConfig(BaseModel):
    """Simplified scraper configuration."""

    model_config = ConfigDict(populate_by_name=True)

    league_code: str = Field(..., alias="leagueCode")
    season: int | None = Field(None, alias="season")
    season_type: str = Field("regular", alias="seasonType")
    start_date: date | None = Field(None, alias="startDate")
    end_date: date | None = Field(None, alias="endDate")

    @field_validator("end_date", mode="after")
    @classmethod
    def cap_end_date_to_reasonable_future(cls, v: date | None) -> date:
        """Ensure end_date is set and within a reasonable future window.

        If end_date is None, defaults to today.
        Allows up to 7 days in the future to support odds fetching for upcoming games.
        Boxscores for future dates simply return no data (graceful no-op).
        """
        from datetime import timedelta

        today = date.today()
        max_future = today + timedelta(days=7)

        if v is None:
            return today
        if v > max_future:
            return max_future
        return v

    # Data type toggles
    boxscores: bool = Field(True, alias="boxscores")
    odds: bool = Field(True, alias="odds")
    social: bool = Field(False, alias="social")
    pbp: bool = Field(False, alias="pbp")
    advanced_stats: bool = Field(False, alias="advancedStats")

    # NOTE: Boxscore date capping is handled by the scraper worker
    # (ScrapeRunManager.run) which computes boxscore_end = min(end, yesterday)
    # independently of the shared end_date. Capping here would silently
    # prevent requesting future odds/pbp windows when boxscores are on.

    # Shared filters
    only_missing: bool = Field(False, alias="onlyMissing")
    updated_before: date | None = Field(None, alias="updatedBefore")

    # Optional book filter
    include_books: list[str] | None = Field(None, alias="books")

    def to_worker_payload(self) -> dict[str, Any]:
        return {
            "league_code": self.league_code.upper(),
            "season": self.season,
            "season_type": self.season_type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "boxscores": self.boxscores,
            "odds": self.odds,
            "social": self.social,
            "pbp": self.pbp,
            "advanced_stats": self.advanced_stats,
            "only_missing": self.only_missing,
            "updated_before": self.updated_before.isoformat() if self.updated_before else None,
            "include_books": self.include_books,
        }


class ScrapeRunCreateRequest(BaseModel):
    config: ScrapeRunConfig
    requested_by: str | None = Field(None, alias="requestedBy")


class ScrapeRunResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    league_code: str
    status: str
    scraper_type: str
    job_id: str | None = None
    season: int | None
    start_date: date | None
    end_date: date | None
    summary: str | None
    error_details: str | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    requested_by: str | None
    config: dict[str, Any] | None = None
