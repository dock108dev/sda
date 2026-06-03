"""Name matching and synthetic player helpers for Masters setup."""

from __future__ import annotations

import re
import unicodedata

from setup_masters_data import _SYNTHETIC_DG_ID_START, MASTERS_AMATEURS_2026
from sqlalchemy import text


def _normalize(name: str) -> str:
    """Normalize a name for fuzzy matching: lowercase, strip accents, punctuation."""
    # Decompose unicode and strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase, strip punctuation except spaces/hyphens
    ascii_name = ascii_name.lower().strip()
    ascii_name = re.sub(r"[^a-z\s-]", "", ascii_name)
    # Collapse whitespace
    ascii_name = re.sub(r"\s+", " ", ascii_name)
    return ascii_name


def _to_last_first(name: str) -> str:
    """Convert 'First Last' to 'last first' for matching."""
    parts = name.strip().split()
    if len(parts) >= 2:
        # Handle multi-word last names: take last word as last name
        # But also handle "Min Woo Lee" → "Lee, Min Woo"
        return f"{parts[-1]} {' '.join(parts[:-1])}"
    return name


def _to_last_comma_first(name: str) -> str:
    """Convert 'First Last' to 'Last, First' (DataGolf convention)."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return name


def _build_name_variants(name: str) -> list[str]:
    """Build multiple normalized variants for matching."""
    norm = _normalize(name)
    variants = [norm]

    # Also try "Last First" ordering
    last_first = _normalize(_to_last_first(name))
    if last_first != norm:
        variants.append(last_first)

    # Handle "J.J." → "jj"
    no_dots = norm.replace(".", "")
    if no_dots != norm:
        variants.append(no_dots)
        variants.append(_normalize(_to_last_first(name.replace(".", ""))))

    return variants



def load_all_players(session) -> dict[str, dict]:
    """Load all players from golf_players, keyed by normalized name."""
    rows = session.execute(
        text("SELECT dg_id, player_name, country, country_code, amateur FROM golf_players")
    ).fetchall()

    by_name: dict[str, dict] = {}
    for r in rows:
        player = {
            "dg_id": r[0],
            "player_name": r[1],
            "country": r[2],
            "country_code": r[3],
            "amateur": r[4],
        }
        # DataGolf format: "Last, First" — normalize both orderings
        dg_name = r[1] or ""
        norm = _normalize(dg_name)
        by_name[norm] = player

        # Also index as "First Last" order
        if "," in dg_name:
            parts = dg_name.split(",", 1)
            flipped = f"{parts[1].strip()} {parts[0].strip()}"
            by_name[_normalize(flipped)] = player

    return by_name


def match_field_to_players(
    field_names: list[str], player_index: dict[str, dict]
) -> tuple[list[dict], list[str]]:
    """Match field names to dg_ids. Returns (matched, unmatched)."""
    matched = []
    unmatched = []

    for name in field_names:
        found = False
        for variant in _build_name_variants(name):
            if variant in player_index:
                p = player_index[variant]
                matched.append({
                    "field_name": name,
                    "dg_id": p["dg_id"],
                    "dg_name": p["player_name"],
                    "country": p["country"],
                    "amateur": name in MASTERS_AMATEURS_2026,
                })
                found = True
                break

        if not found:
            unmatched.append(name)

    return matched, unmatched


def _next_synthetic_dg_id(session) -> int:
    """Get the next available synthetic dg_id (900_000+)."""
    row = session.execute(
        text("SELECT COALESCE(MAX(dg_id), :start - 1) FROM golf_players WHERE dg_id >= :start"),
        {"start": _SYNTHETIC_DG_ID_START},
    ).fetchone()
    return row[0] + 1


def create_unmatched_players(
    session, unmatched_names: list[str], *, dry_run: bool = False
) -> list[dict]:
    """Create golf_players entries for unmatched players with synthetic dg_ids.

    Returns list of dicts with field_name, dg_id, dg_name, amateur flag.
    """
    if not unmatched_names:
        return []

    if dry_run:
        print(f"  [DRY RUN] Would create {len(unmatched_names)} player entries")
        return [
            {"field_name": n, "dg_id": _SYNTHETIC_DG_ID_START + i, "dg_name": _to_last_comma_first(n), "amateur": n in MASTERS_AMATEURS_2026}
            for i, n in enumerate(unmatched_names)
        ]

    next_id = _next_synthetic_dg_id(session)
    created = []

    sql = text("""
        INSERT INTO golf_players (dg_id, player_name, amateur, updated_at)
        VALUES (:dg_id, :player_name, :amateur, NOW())
        ON CONFLICT (dg_id) DO UPDATE SET
            player_name = EXCLUDED.player_name,
            amateur = EXCLUDED.amateur,
            updated_at = NOW()
    """)

    for name in unmatched_names:
        dg_id = next_id
        is_amateur = name in MASTERS_AMATEURS_2026
        dg_name = _to_last_comma_first(name)
        session.execute(sql, {
            "dg_id": dg_id,
            "player_name": dg_name,
            "amateur": is_amateur,
        })
        created.append({
            "field_name": name,
            "dg_id": dg_id,
            "dg_name": dg_name,
            "country": None,
            "amateur": is_amateur,
        })
        next_id += 1

    session.commit()
    return created
