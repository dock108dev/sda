"""Team persistence helpers.

Handles team upsert and lookup logic, including NCAAB-specific name normalization.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..normalization import normalize_team_name
from ..utils.datetime_utils import now_utc
from ..utils.db_queries import count_team_games

_LOG_COUNTERS: dict[str, int] = {}
_LOG_SAMPLE = 50


def _should_log(event_key: str, sample: int = _LOG_SAMPLE) -> bool:
    count = _LOG_COUNTERS.get(event_key, 0) + 1
    _LOG_COUNTERS[event_key] = count
    return count % sample == 1

# Some feeds (especially NCAAB) may omit abbreviations. Our DB schema requires
# a non-null abbreviation, so we derive a deterministic fallback when missing.
_ABBR_STOPWORDS = {"of", "the", "and", "at"}


def _derive_abbreviation(team_name: str, strip_mascots: bool = True) -> str:
    """Derive a deterministic, non-empty team abbreviation from a team name.

    This is a fallback for feeds that omit abbreviations. It is NOT intended to
    be perfect; it is intended to be stable and satisfy DB constraints.

    When strip_mascots is True (default), mascot words from _NCAAB_STOPWORDS
    are removed before deriving the abbreviation. This prevents garbage codes
    like "ACT" for "Alabama Crimson Tide" (should use school name only).
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", (team_name or "")).strip()
    if not cleaned:
        return "UNK"

    tokens = [t for t in cleaned.split() if t and t.lower() not in _ABBR_STOPWORDS]
    if not tokens:
        tokens = cleaned.split()

    # Strip mascot words so abbreviations are school-based
    if strip_mascots:
        school_tokens = [t for t in tokens if t.lower() not in _NCAAB_STOPWORDS]
        if school_tokens:
            tokens = school_tokens

    # Common patterns like "UC-Irvine" -> "UCI"
    first = tokens[0].upper()
    if first in {"UC", "UNC"} and len(tokens) > 1:
        second = tokens[1].upper()
        return (first + second[:2])[:6]

    # Single-word school names: use first 4 chars (e.g., "Duke" -> "DUKE")
    if len(tokens) == 1:
        return tokens[0].upper()[:4] or "UNK"

    # Multi-word school names: take initials (e.g., "San Diego State" -> "SDS")
    abbr = "".join(t[0].upper() for t in tokens[:6])

    # Ensure minimum length of 3 when possible by extending with more letters.
    if len(abbr) < 3:
        last = tokens[-1].upper()
        i = 1
        while len(abbr) < 3 and i < len(last):
            abbr += last[i]
            i += 1

    if not abbr:
        abbr = tokens[0].upper()[:3] or "UNK"

    return abbr[:6]

# Known tricky NCAAB name overrides (requested -> canonical DB name)
_NCAAB_OVERRIDES = {
    "george washington colonials": "George Washington",
    "arkansas-pine bluff golden lions": "Arkansas-Pine Bluff",
    "south carolina upstate spartans": "South Carolina Upstate Spartans",
    "siu-edwardsville cougars": "SIU Edwardsville",
    # HBCU teams that collide with Power conference after normalization
    "alabama a&m bulldogs": "Alabama A&M Bulldogs",
    "north carolina central eagles": "North Carolina Central Eagles",
    "maryland eastern shore hawks": "Maryland-Eastern Shore Hawks",
    "maryland-eastern shore hawks": "Maryland-Eastern Shore Hawks",
    "texas southern tigers": "Texas Southern Tigers",
    "grambling tigers": "Grambling St Tigers",
    "grambling state tigers": "Grambling St Tigers",
    "howard bison": "Howard Bison",
    "coppin state eagles": "Coppin St Eagles",
}

# Common NCAAB mascot/color tokens that should not drive matching.
_NCAAB_STOPWORDS = {
    # Mascots
    "aggies", "anteaters", "bearcats", "beacons", "bears", "bearkats",
    "beavers", "bison", "blazers", "blue", "bobcats", "boilermakers",
    "bonnies", "braves", "broncos", "bruins", "buccaneers", "buckeyes",
    "bulldogs", "bulls", "camels", "cardinals", "catamounts", "cavaliers",
    "chanticleers", "chargers", "colonels", "commodores", "cornhuskers",
    "cougars", "cowboys", "crimson", "crusaders", "cyclones", "deacons",
    "demons", "devils", "dolphins", "dons", "dragons", "ducks", "dukes",
    "eagles", "explorers", "falcons", "fighting", "flames", "flashes",
    "flyers", "friars", "gaels", "gamecocks", "gators", "golden", "gophers",
    "governors", "grizzlies", "hawks", "hilltoppers", "hokies", "hornets",
    "hoyas", "hurricanes", "huskies", "illini", "islanders", "jackrabbits",
    "jaguars", "jayhawks", "keydets", "knights", "lancers", "leopards",
    "lions", "lobos", "longhorns", "lumberjacks", "mean", "miners",
    "minutemen", "mocs", "monarchs", "mountaineers", "musketeers", "mustangs",
    "nittany", "norse", "orange", "owls", "paladins", "panthers", "patriots",
    "peacocks", "penguins", "phoenix", "pilots", "pioneers", "pirates",
    "pride", "privateers", "purple", "quakers", "racers", "ragin",
    "raiders", "ramblers", "rams", "rattlers", "razorbacks", "rebels",
    "red", "redbirds", "redhawks", "retrievers", "revolutionaries",
    "roadrunners", "rockets", "royals", "salukis", "scarlet", "seahawks",
    "seminoles", "shockers", "skyhawks", "sooners", "spartans",
    "spiders", "stags", "storm", "terrapins", "terriers", "texans",
    "thundering", "tide", "tigers", "tommies", "toreros", "trailblazers",
    "trojans", "volunteers", "warriors", "wave", "waves", "wildcats",
    "wolf", "wolfpack", "wolverines", "wolves", "yellow", "zips",
    # Color/descriptor tokens frequently paired with mascots
    "gold", "green", "white", "bluejays", "maroon",
}

# Abbreviation/short-name expansions frequently used by books.
_NCAAB_ABBREV_EXPANSIONS = {
    "byu": "brigham young",
    "uab": "alabama birmingham",
    "uconn": "connecticut",
    "lsu": "louisiana state",
    "usc": "southern california",
    "smu": "southern methodist",
    "tcu": "texas christian",
    "ucf": "central florida",
    "fiu": "florida international",
    "vcu": "virginia commonwealth",
    "utrgv": "texas rio grande valley",
    "sfa": "stephen f austin",
    "fdu": "fairleigh dickinson",
    "siue": "siu edwardsville",
    "utep": "texas el paso",
    "utsa": "texas san antonio",
    "uncg": "north carolina greensboro",
    "uncw": "north carolina wilmington",
    "unc": "north carolina",
    "umkc": "missouri kansas city",
    "liu": "long island",
    "gw": "george washington",
    "fau": "florida atlantic",
    "csu": "colorado state",
}


if TYPE_CHECKING:
    from ..models import TeamIdentity


def _normalize_ncaab_name_for_matching(name: str) -> str:
    """Normalize NCAAB team name for matching purposes.

    Handles common variations:
    - Expands common abbreviations (BYU -> Brigham Young, UConn -> Connecticut, etc.)
    - Drops mascots/colors (Tigers, Golden, Red, etc.) so school/city drives the match
    - "St" -> "State" (but NOT "St." which is "Saint" like "St. John's")
    - "U" -> "University"
    - Removes parenthetical qualifiers (e.g., "(NY)")
    - Removes punctuation
    - Normalizes whitespace
    - Returns lowercase for case-insensitive comparison
    """
    normalized = name.strip()
    # Drop parenthetical qualifiers to allow matching "St. John's (NY)" with "St. John's Red Storm"
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    # Only convert "St" to "State" if it's NOT followed by a period
    # This prevents "St. John's" from becoming "State. John's"
    normalized = re.sub(r"\bSt(?![.])\s+", "State ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bSt(?![.])$", "State", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bU\b", "University", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[.,\-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.lower()

    tokens: list[str] = []
    for token in normalized.split(" "):
        if not token:
            continue
        expanded = _NCAAB_ABBREV_EXPANSIONS.get(token, token)
        for piece in expanded.split(" "):
            piece = piece.strip()
            if not piece or piece in _NCAAB_STOPWORDS:
                continue
            tokens.append(piece)

    if not tokens:
        return normalized  # fallback to original lowercased form

    return " ".join(tokens)


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

    abbreviation = feed_abbreviation or _derive_abbreviation(team_name)
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
        )
        .returning(db_models.SportsTeam.id)
    )
    result = session.execute(stmt).scalar_one()
    return int(result)


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
        if override_key in _NCAAB_OVERRIDES:
            team_name = _NCAAB_OVERRIDES[override_key]

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
            normalized_input = _normalize_ncaab_name_for_matching(team_name)
            all_teams_stmt = (
                select(db_models.SportsTeam.id, db_models.SportsTeam.name, db_models.SportsTeam.short_name)
                .where(db_models.SportsTeam.league_id == league_id)
            )
            all_teams = session.execute(all_teams_stmt).all()
            def _ncaab_substring_match(a: str, b: str) -> bool:
                shorter, longer = sorted([a, b], key=len)
                return shorter in longer and len(shorter) / len(longer) >= 0.8

            for team_id, db_name, db_short_name in all_teams:
                db_name_norm = _normalize_ncaab_name_for_matching(db_name or "")
                db_short_norm = _normalize_ncaab_name_for_matching(db_short_name or "")
                if (
                    normalized_input == db_name_norm or
                    normalized_input == db_short_norm or
                    _ncaab_substring_match(normalized_input, db_name_norm) or
                    _ncaab_substring_match(normalized_input, db_short_norm)
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
        normalized_input = _normalize_ncaab_name_for_matching(team_name)
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
                db_name_norm = _normalize_ncaab_name_for_matching(team.name or "")
                db_short_norm = _normalize_ncaab_name_for_matching(team.short_name or "")
                if normalized_input == db_name_norm or normalized_input == db_short_norm:
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
                normalized_input = _normalize_ncaab_name_for_matching(team_name)
                db_name_norm = _normalize_ncaab_name_for_matching(team.name or "")
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
