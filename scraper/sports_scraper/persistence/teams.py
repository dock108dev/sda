"""Team persistence helpers.

Handles team upsert and lookup logic, including NCAAB-specific name normalization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..normalization import normalize_team_name
from ..utils.datetime_utils import now_utc
from ..utils.db_queries import count_team_games
from . import team_name_normalization as _team_names

if TYPE_CHECKING:
    from ..models import TeamIdentity

_LOG_COUNTERS: dict[str, int] = {}
_LOG_SAMPLE = 50


def _should_log(event_key: str, sample: int = _LOG_SAMPLE) -> bool:
    count = _LOG_COUNTERS.get(event_key, 0) + 1
    _LOG_COUNTERS[event_key] = count
    return count % sample == 1

def _upsert_team(session: Session, league_id: int, identity: TeamIdentity) -> int:
    """Upsert a team, creating or updating as needed.

    Note: abbreviations must be non-null in the DB schema. If a feed omits an
    abbreviation (common in some NCAAB sources), we derive a deterministic
    fallback to satisfy the constraint.
    """
    team_name = identity.name
    short_name = identity.short_name or team_name
    league = session.get(db_models.SportsLeague, league_id)
    league_code = league.code if league else None

    # Normalize team name to canonical form so that all sources converge to
    # the same row (e.g., "Los Angeles Clippers" → "LA Clippers").
    feed_abbreviation = identity.abbreviation
    if league_code and league_code != "NCAAB":
        canonical_name, canonical_abbr = normalize_team_name(league_code, team_name)
        if canonical_name != team_name:
            team_name = canonical_name
        if canonical_abbr and feed_abbreviation is None:
            feed_abbreviation = canonical_abbr
    elif league_code == "NCAAB":
        # NCAAB has hundreds of teams with wildly different naming across
        # sources (CBB API: "Yale", ESPN: "Yale Bulldogs").  Before creating
        # a new team row, check if an existing team matches via fuzzy lookup.
        existing_id = _find_team_by_name(
            session, league_id, team_name, team_abbr=feed_abbreviation,
        )
        if existing_id is not None:
            return existing_id

    abbreviation = feed_abbreviation or _team_names._derive_abbreviation(team_name)
    if feed_abbreviation is None and _should_log("team_abbreviation_derived", sample=25):
        logger.warning(
            "team_abbreviation_derived",
            league_code=league_code,
            team_name=team_name,
            derived_abbreviation=abbreviation,
        )

    # If the feed didn't provide an abbreviation, never overwrite a pre-existing one.
    abbreviation_update_value = (
        abbreviation if feed_abbreviation is not None else db_models.SportsTeam.abbreviation
    )

    # Only update when at least one tracked column actually changed. This
    # avoids no-op writes that would still take a row X-lock and produce
    # cross-worker deadlocks when odds and boxscore writers concurrently
    # touch the same teams.
    change_predicates = [
        db_models.SportsTeam.short_name.is_distinct_from(short_name),
        db_models.SportsTeam.external_ref.is_distinct_from(identity.external_ref),
    ]
    if feed_abbreviation is not None:
        change_predicates.append(
            db_models.SportsTeam.abbreviation.is_distinct_from(abbreviation)
        )

    stmt = (
        insert(db_models.SportsTeam)
        .values(
            league_id=league_id,
            external_ref=identity.external_ref,
            name=team_name,
            short_name=short_name,
            abbreviation=abbreviation,
            location=None,
            external_codes={},
        )
        .on_conflict_do_update(
            index_elements=["league_id", "name"],
            set_={
                "short_name": short_name,
                "abbreviation": abbreviation_update_value,
                "external_ref": identity.external_ref,
                "updated_at": now_utc(),
            },
            where=or_(*change_predicates),
        )
        .returning(db_models.SportsTeam.id)
    )
    result = session.execute(stmt).scalar()
    if result is not None:
        return int(result)

    # WHERE filtered the conflict path (row exists, nothing to update).
    # Fetch the existing id directly.
    existing_id = session.execute(
        select(db_models.SportsTeam.id)
        .where(db_models.SportsTeam.league_id == league_id)
        .where(db_models.SportsTeam.name == team_name)
    ).scalar_one()
    return int(existing_id)


def _find_team_by_name(
    session: Session,
    league_id: int,
    team_name: str,
    team_abbr: str | None = None,
) -> int | None:
    """Find existing team by name (exact or normalized match).

    Tries multiple strategies:
    1. Exact match on name or short_name
    2. Normalized match for NCAAB (handles "St" vs "State", etc.)
    3. If team_name contains a space, try matching the first word (city name) - non-NCAAB only
    4. Match by abbreviation (skipped for NCAAB to avoid collisions)
    5. Prefer teams with more games (more established)
    """
    def team_usage(team_id: int) -> int:
        return count_team_games(session, team_id)

    league = session.get(db_models.SportsLeague, league_id)
    league_code = league.code if league else None

    # Apply overrides for NCAAB before matching
    if league_code == "NCAAB":
        override_key = team_name.lower().strip()
        if override_key in _team_names._NCAAB_OVERRIDES:
            team_name = _team_names._NCAAB_OVERRIDES[override_key]

    candidate_ids: list[int] = []

    if league_code == "NCAAB":
        canonical_name, _ = normalize_team_name(league_code, team_name)
        exact_match_stmt = (
            select(db_models.SportsTeam.id)
            .where(db_models.SportsTeam.league_id == league_id)
            .where(
                or_(
                    db_models.SportsTeam.name == team_name,
                    db_models.SportsTeam.name == canonical_name,
                    db_models.SportsTeam.short_name == team_name,
                    db_models.SportsTeam.short_name == canonical_name,
                    func.lower(db_models.SportsTeam.name) == func.lower(team_name),
                    func.lower(db_models.SportsTeam.name) == func.lower(canonical_name),
                    func.lower(db_models.SportsTeam.short_name) == func.lower(team_name),
                    func.lower(db_models.SportsTeam.short_name) == func.lower(canonical_name),
                )
            )
        )
        exact_matches = [row[0] for row in session.execute(exact_match_stmt).all()]
        candidate_ids.extend(exact_matches)

        if not exact_matches:
            normalized_input = _team_names._normalize_ncaab_name_for_matching(team_name)
            all_teams_stmt = (
                select(db_models.SportsTeam.id, db_models.SportsTeam.name, db_models.SportsTeam.short_name)
                .where(db_models.SportsTeam.league_id == league_id)
            )
            all_teams = session.execute(all_teams_stmt).all()
            def _ncaab_substring_match(a: str, b: str) -> bool:
                shorter, longer = sorted([a, b], key=len)
                return shorter in longer and len(shorter) / len(longer) >= 0.8

            for team_id, db_name, db_short_name in all_teams:
                db_name_norm = _team_names._normalize_ncaab_name_for_matching(db_name or "")
                db_short_norm = _team_names._normalize_ncaab_name_for_matching(db_short_name or "")
                if (
                    normalized_input in (db_name_norm, db_short_norm) or _ncaab_substring_match(normalized_input, db_name_norm) or _ncaab_substring_match(normalized_input, db_short_norm)
                ):
                    candidate_ids.append(team_id)
    else:
        exact_match_stmt = (
            select(db_models.SportsTeam.id)
            .where(db_models.SportsTeam.league_id == league_id)
            .where(
                or_(
                    db_models.SportsTeam.name == team_name,
                    db_models.SportsTeam.short_name == team_name,
                    func.lower(db_models.SportsTeam.name) == func.lower(team_name),
                    func.lower(db_models.SportsTeam.short_name) == func.lower(team_name),
                )
            )
            .limit(1)
        )
        exact_match_id = session.execute(exact_match_stmt).scalar()
        if exact_match_id is not None:
            candidate_ids.append(exact_match_id)

        if team_name and " " in team_name:
            first_word = team_name.split()[0]
            # For short first words (like "LA", "NY"), only do exact first-word match,
            # not prefix matching, to avoid confusing multi-team cities
            # (e.g., "LA Clippers" vs "LA Lakers", "NY Giants" vs "NY Jets")
            if len(first_word) <= 3:
                # Short prefix: only exact match on full name, no prefix expansion
                base_stmt = (
                    select(db_models.SportsTeam.id)
                    .where(db_models.SportsTeam.league_id == league_id)
                    .where(
                        or_(
                            func.lower(db_models.SportsTeam.name) == func.lower(team_name),
                            func.lower(db_models.SportsTeam.short_name) == func.lower(team_name),
                        )
                    )
                )
            else:
                # Longer first word: safe to do prefix matching
                base_stmt = (
                    select(db_models.SportsTeam.id)
                    .where(db_models.SportsTeam.league_id == league_id)
                    .where(
                        or_(
                            db_models.SportsTeam.name == first_word,
                            db_models.SportsTeam.short_name == first_word,
                            func.lower(db_models.SportsTeam.name) == func.lower(first_word),
                            func.lower(db_models.SportsTeam.short_name) == func.lower(first_word),
                            func.lower(db_models.SportsTeam.name).like(func.lower(first_word) + "%"),
                            func.lower(db_models.SportsTeam.short_name).like(func.lower(first_word) + "%"),
                        )
                    )
                )
            base_matches = [row[0] for row in session.execute(base_stmt).all()]
            candidate_ids.extend(base_matches)
        elif team_name:
            single_word_stmt = (
                select(db_models.SportsTeam.id)
                .where(db_models.SportsTeam.league_id == league_id)
                .where(
                    or_(
                        func.lower(db_models.SportsTeam.name).like(func.lower(team_name) + "%"),
                        func.lower(db_models.SportsTeam.short_name).like(func.lower(team_name) + "%"),
                    )
                )
            )
            single_word_matches = [row[0] for row in session.execute(single_word_stmt).all()]
            candidate_ids.extend(single_word_matches)

    if team_abbr:
        stmt = (
            select(db_models.SportsTeam.id)
            .where(db_models.SportsTeam.league_id == league_id)
            .where(func.upper(db_models.SportsTeam.abbreviation) == func.upper(team_abbr))
        )
        abbr_matches = [row[0] for row in session.execute(stmt).all()]
        candidate_ids.extend(abbr_matches)

    if not candidate_ids:
        return None

    seen = set()
    unique_candidates = []
    for cid in candidate_ids:
        if cid not in seen:
            seen.add(cid)
            unique_candidates.append(cid)

    # Drop obviously bogus candidates (empty/very short names)
    filtered_candidates: list[int] = []
    for cid in unique_candidates:
        team = session.get(db_models.SportsTeam, cid)
        if not team or not team.name or len(team.name.strip()) < 3:
            continue
        filtered_candidates.append(cid)
    unique_candidates = filtered_candidates

    if not unique_candidates:
        return None

    if league_code == "NCAAB" and len(unique_candidates) > 1:
        canonical_name, _ = normalize_team_name(league_code, team_name)
        normalized_input = _team_names._normalize_ncaab_name_for_matching(team_name)
        exact_matches = []
        for cid in unique_candidates:
            team = session.get(db_models.SportsTeam, cid)
            if not team:
                continue
            if (
                team.name.lower() == team_name.lower() or
                team.name.lower() == canonical_name.lower() or
                team.short_name.lower() == team_name.lower() or
                team.short_name.lower() == canonical_name.lower()
            ):
                exact_matches.append(cid)
            elif normalized_input:
                db_name_norm = _team_names._normalize_ncaab_name_for_matching(team.name or "")
                db_short_norm = _team_names._normalize_ncaab_name_for_matching(team.short_name or "")
                if normalized_input in (db_name_norm, db_short_norm):
                    exact_matches.append(cid)

        if exact_matches:
            unique_candidates = exact_matches
        elif unique_candidates:
            team = session.get(db_models.SportsTeam, unique_candidates[0])
            if _should_log("ncaab_team_match_ambiguous", sample=20):
                logger.warning(
                    "ncaab_team_match_ambiguous",
                    requested_name=team_name,
                    canonical_name=canonical_name,
                    matched_team_id=unique_candidates[0],
                    matched_team_name=team.name if team else None,
                    total_candidates=len(unique_candidates),
                )

    def team_score(team_id: int) -> tuple[int, int, int, int, int]:
        """
        Score teams for selection.
        For NCAAB: prioritize usage (games), then canonical match, then shorter name.
        For others: prioritize exact name match, then canonical, then full name, then usage.
        """
        team = session.get(db_models.SportsTeam, team_id)
        if not team:
            return (0, 0, 0, 0, 0)

        # Check if this team's name directly matches the requested name (highest priority)
        exact_name_match = (
            team.name.lower() == team_name.lower() or
            (team.short_name and team.short_name.lower() == team_name.lower())
        )

        matches_canonical = False
        normalized_contains = False
        if league_code:
            canonical_name, _ = normalize_team_name(league_code, team.name)
            matches_canonical = (team.name == canonical_name)
            if league_code == "NCAAB":
                normalized_input = _team_names._normalize_ncaab_name_for_matching(team_name)
                db_name_norm = _team_names._normalize_ncaab_name_for_matching(team.name or "")
                normalized_contains = normalized_input and (normalized_input in db_name_norm or db_name_norm in normalized_input)

        has_full_name = " " in team.name
        usage = team_usage(team_id)
        if league_code == "NCAAB":
            # Prefer exact name match, then canonical, then normalized contains, then usage, then shorter name
            return (
                1 if exact_name_match else 0,
                1 if matches_canonical else 0,
                1 if normalized_contains else 0,
                usage,
                -len(team.name or ""),
            )
        # For non-NCAAB: exact name match is highest priority
        return (100000 if exact_name_match else 0, 10000 if matches_canonical else 0, 1000 if has_full_name else 0, usage, 0)

    scored_candidates = [(team_score(cid), cid) for cid in unique_candidates]
    scored_candidates.sort(reverse=True)
    best_id = scored_candidates[0][1]

    return best_id
