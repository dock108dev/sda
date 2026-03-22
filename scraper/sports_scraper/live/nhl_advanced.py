"""NHL MoneyPuck-derived advanced stats aggregation.

Downloads MoneyPuck season CSV files containing pre-computed xGoal
probabilities for every shot, caches locally, and aggregates into
team-level, skater-level, and goalie-level advanced stats.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..logging import logger
from ..utils.cache import APICache

# MoneyPuck shot data download URL (ZIP containing a CSV)
MONEYPUCK_ZIP_URL = "https://peter-tanner.com/moneypuck/downloads/shots_{season}.zip"

# High danger threshold: shots from <= 20 feet
HIGH_DANGER_DISTANCE_FT = 20
# Medium danger: 20 < distance <= 40 feet
MEDIUM_DANGER_DISTANCE_FT = 40

# Cache re-download interval: once per day (seconds)
CSV_CACHE_TTL_SECONDS = 86400


@dataclass
class TeamAdvancedAggregates:
    """Raw aggregated stats for one team in a game."""

    team: str = ""
    is_home: bool = False
    # xGoals
    xgoals_for: float = 0.0
    xgoals_against: float = 0.0
    # Shot attempts (Corsi = SOG + MISS + BLOCK, Fenwick = SOG + MISS)
    shots_on_goal: int = 0
    missed_shots: int = 0
    blocked_shots: int = 0
    goals: int = 0
    # Danger zones (for)
    high_danger_shots: int = 0
    high_danger_goals: int = 0
    # Opposing stats filled by cross-reference
    shots_on_goal_against: int = 0
    missed_shots_against: int = 0
    blocked_shots_against: int = 0
    goals_against: int = 0
    xgoals_against_total: float = 0.0
    high_danger_shots_against: int = 0
    high_danger_goals_against: int = 0


@dataclass
class SkaterAggregates:
    """Per-skater aggregated stats from shot data."""

    player_id: str = ""
    player_name: str = ""
    team: str = ""
    is_home: bool = False
    # xGoals on ice
    xgoals_for: float = 0.0
    xgoals_against: float = 0.0
    # Individual shots/goals
    shots: int = 0
    goals: int = 0


@dataclass
class GoalieAggregates:
    """Per-goalie aggregated stats from shot data."""

    player_id: str = ""
    player_name: str = ""
    team: str = ""
    is_home: bool = False
    # Shots faced
    xgoals_against: float = 0.0
    goals_against: int = 0
    shots_against: int = 0
    # Danger zone breakdowns
    high_danger_shots: int = 0
    high_danger_goals: int = 0
    medium_danger_shots: int = 0
    medium_danger_goals: int = 0
    low_danger_shots: int = 0
    low_danger_goals: int = 0


def _safe_float(value: str, default: float = 0.0) -> float:
    """Safely parse a float from CSV string."""
    if not value or value.strip() == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: str, default: int = 0) -> int:
    """Safely parse an int from CSV string."""
    if not value or value.strip() == "":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def _classify_danger(distance: float) -> str:
    """Classify shot danger zone based on distance."""
    if distance <= HIGH_DANGER_DISTANCE_FT:
        return "high"
    if distance <= MEDIUM_DANGER_DISTANCE_FT:
        return "medium"
    return "low"




class NHLAdvancedStatsFetcher:
    """Fetches MoneyPuck CSV data and aggregates NHL advanced stats.

    Downloads the full-season shot CSV, caches it locally, and filters
    by game_id to produce team-level, skater-level, and goalie-level
    advanced statistics.
    """

    def __init__(self, cache_dir: str | Path = "./game_data") -> None:
        self._cache = APICache(cache_dir, "moneypuck")
        self._csv_timestamps: dict[int, float] = {}

    def _should_redownload(self, season: int) -> bool:
        """Check if the cached CSV is stale (older than 1 day)."""
        cache_key = f"shots_{season}"
        cache_path = self._cache._get_cache_path(cache_key)
        if not cache_path.exists():
            return True

        file_age = time.time() - cache_path.stat().st_mtime
        return file_age > CSV_CACHE_TTL_SECONDS

    def _download_season_csv(self, season: int) -> str:
        """Download the MoneyPuck season ZIP, extract the CSV, and cache it.

        MoneyPuck publishes shot data as ZIP archives (shots_{season}.zip)
        containing a single CSV file.

        Returns the raw CSV text content.
        """
        import zipfile

        cache_key = f"shots_{season}"

        # Check if we have a fresh-enough cached version
        if not self._should_redownload(season):
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("nhl_moneypuck_cache_hit", season=season)
                return cached

        url = MONEYPUCK_ZIP_URL.format(season=season)
        logger.info("nhl_moneypuck_download_start", season=season, url=url)

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.get(url)
                response.raise_for_status()

            # Extract CSV from the ZIP archive
            zip_bytes = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_bytes) as zf:
                csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_names:
                    raise ValueError(f"No CSV file found in shots_{season}.zip")
                csv_text = zf.read(csv_names[0]).decode("utf-8")

            # Cache the extracted CSV text (not the ZIP)
            self._cache.put(cache_key, csv_text)
            self._csv_timestamps[season] = time.time()

            logger.info(
                "nhl_moneypuck_download_complete",
                season=season,
                csv_size_kb=len(csv_text) // 1024,
                zip_size_kb=len(response.content) // 1024,
            )
            return csv_text

        except httpx.HTTPError as exc:
            logger.error(
                "nhl_moneypuck_download_failed",
                season=season,
                url=url,
                error=str(exc),
            )
            raise

    def fetch_game_shots(self, nhl_game_pk: int, season: int) -> list[dict]:
        """Download season CSV if not cached, filter to this game's shots.

        Args:
            nhl_game_pk: The NHL game primary key (integer).
            season: The season year (e.g. 2025 for the 2025-26 season).

        Returns:
            List of shot dicts from the CSV for this game.
        """
        csv_text = self._download_season_csv(season)

        game_pk_str = str(nhl_game_pk)
        shots: list[dict] = []

        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            if row.get("game_id") == game_pk_str:
                shots.append(row)

        logger.info(
            "nhl_moneypuck_game_shots",
            nhl_game_pk=nhl_game_pk,
            season=season,
            shot_count=len(shots),
        )
        return shots

    def aggregate_team_stats(
        self, shots: list[dict], home_team: str
    ) -> dict[str, TeamAdvancedAggregates]:
        """Aggregate shots into home/away team advanced stats.

        Args:
            shots: List of shot dicts from the MoneyPuck CSV.
            home_team: The home team abbreviation for classification.

        Returns:
            Dict with "home" and "away" keys mapped to TeamAdvancedAggregates.
        """
        home = TeamAdvancedAggregates(team=home_team, is_home=True)
        away = TeamAdvancedAggregates(team="", is_home=False)

        # Determine away team from data
        for shot in shots:
            if _safe_int(shot.get("isHomeTeam", "0")) == 0:
                away.team = shot.get("team", "")
                break

        for shot in shots:
            is_home_team = _safe_int(shot.get("isHomeTeam", "0")) == 1
            team_agg = home if is_home_team else away
            opp_agg = away if is_home_team else home
            event = shot.get("event", "").upper()
            xgoal = _safe_float(shot.get("xGoal", "0"))
            distance = _safe_float(shot.get("arenaAdjustedShotDistance", "999"))
            danger = _classify_danger(distance)
            is_goal = event == "GOAL"

            # xGoals
            team_agg.xgoals_for += xgoal
            opp_agg.xgoals_against_total += xgoal

            # Shot attempt classification
            if event == "SHOT":
                team_agg.shots_on_goal += 1
                opp_agg.shots_on_goal_against += 1
            elif event == "GOAL":
                team_agg.shots_on_goal += 1
                team_agg.goals += 1
                opp_agg.shots_on_goal_against += 1
                opp_agg.goals_against += 1
            elif event == "MISS":
                team_agg.missed_shots += 1
                opp_agg.missed_shots_against += 1
            # BLOCK events: the blocking team gets credit, shooting team gets blocked_shots
            # In MoneyPuck, the row is attributed to the shooting team
            # so we count it as a blocked shot attempt for the shooting team

            # Danger zones (for the shooting team)
            if event in ("SHOT", "GOAL", "MISS") and danger == "high":
                team_agg.high_danger_shots += 1
                opp_agg.high_danger_shots_against += 1
                if is_goal:
                    team_agg.high_danger_goals += 1
                    opp_agg.high_danger_goals_against += 1

        return {"home": home, "away": away}

    def aggregate_skater_stats(
        self, shots: list[dict], toi_minutes: dict[str, float] | None = None
    ) -> list[SkaterAggregates]:
        """Aggregate per-skater stats from shot data.

        Args:
            shots: List of shot dicts from the MoneyPuck CSV.
            toi_minutes: Optional dict of player_id -> TOI in minutes
                for per-60 rate calculations.

        Returns:
            List of SkaterAggregates, one per shooter.
        """
        # Key: (team, player_id) -> SkaterAggregates
        skaters: dict[tuple[str, str], SkaterAggregates] = {}

        for shot in shots:
            shooter_id = shot.get("shooterPlayerId", "")
            if not shooter_id:
                continue

            team = shot.get("team", "")
            is_home = _safe_int(shot.get("isHomeTeam", "0")) == 1
            event = shot.get("event", "").upper()
            xgoal = _safe_float(shot.get("xGoal", "0"))

            key = (team, shooter_id)
            if key not in skaters:
                skaters[key] = SkaterAggregates(
                    player_id=str(shooter_id),
                    player_name=str(shooter_id),  # MoneyPuck CSV uses IDs; name resolved at ingestion
                    team=team,
                    is_home=is_home,
                )

            agg = skaters[key]
            agg.xgoals_for += xgoal

            if event in ("SHOT", "GOAL"):
                agg.shots += 1
            if event == "GOAL":
                agg.goals += 1

        return list(skaters.values())

    def aggregate_goalie_stats(self, shots: list[dict]) -> list[GoalieAggregates]:
        """Aggregate per-goalie stats from shot data.

        Args:
            shots: List of shot dicts from the MoneyPuck CSV.

        Returns:
            List of GoalieAggregates, one per goalie who faced shots.
        """
        # Key: goalie_id -> GoalieAggregates
        goalies: dict[str, GoalieAggregates] = {}

        for shot in shots:
            goalie_id = shot.get("goalieIdForShot", "")
            if not goalie_id or goalie_id == "0":
                continue

            event = shot.get("event", "").upper()
            xgoal = _safe_float(shot.get("xGoal", "0"))
            distance = _safe_float(shot.get("arenaAdjustedShotDistance", "999"))
            danger = _classify_danger(distance)

            # Goalie's team is the opposite of the shooting team
            is_shooter_home = _safe_int(shot.get("isHomeTeam", "0")) == 1
            goalie_is_home = not is_shooter_home
            if goalie_id not in goalies:
                goalies[goalie_id] = GoalieAggregates(
                    player_id=str(goalie_id),
                    player_name=str(goalie_id),  # Resolved at ingestion
                    team="",  # Will be set from opposing team
                    is_home=goalie_is_home,
                )

            agg = goalies[goalie_id]

            # Only count shots on goal and goals (not misses) against goalie
            if event in ("SHOT", "GOAL"):
                agg.shots_against += 1
                agg.xgoals_against += xgoal

                is_goal = event == "GOAL"
                if is_goal:
                    agg.goals_against += 1

                if danger == "high":
                    agg.high_danger_shots += 1
                    if is_goal:
                        agg.high_danger_goals += 1
                elif danger == "medium":
                    agg.medium_danger_shots += 1
                    if is_goal:
                        agg.medium_danger_goals += 1
                else:
                    agg.low_danger_shots += 1
                    if is_goal:
                        agg.low_danger_goals += 1

        return list(goalies.values())
