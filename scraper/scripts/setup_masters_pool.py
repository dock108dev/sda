#!/usr/bin/env python3
"""Set up the RVCC Masters 2026 pool with the official field.

This script:
1. Ensures The Masters tournament exists in the DB
2. Maps the official field list to DataGolf player IDs
3. Creates golf_players entries for unmatched players (amateurs, etc.)
4. Inserts the full field into golf_tournament_fields
5. Creates the RVCC pool record
6. Sets the pool to 'open' so the frontend can accept entries

When DataGolf later publishes their field via sync_field, their entries
upsert by (tournament_id, dg_id). Players we created with synthetic IDs
stay alongside; players DataGolf knows get real leaderboard data.

Usage:
    python scripts/setup_masters_pool.py              # full setup (draft)
    python scripts/setup_masters_pool.py --open       # setup + open for entries
    python scripts/setup_masters_pool.py --field-only # just show field mapping
    python scripts/setup_masters_pool.py --dry-run    # preview without DB writes
    python scripts/setup_masters_pool.py --other "Luke Donald, Zach Blair"  # add extra players
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

from sqlalchemy import text

script_dir = Path(__file__).resolve().parent
scraper_dir = script_dir.parent
sys.path.insert(0, str(scraper_dir))

api_dir = scraper_dir.parent / "api"
if str(api_dir) not in sys.path:
    sys.path.append(str(api_dir))

from sports_scraper.db import get_session  # noqa: E402

# ---------------------------------------------------------------------------
# 2026 Masters Official Field
# ---------------------------------------------------------------------------

MASTERS_FIELD_2026 = [
    "Ludvig Aberg",
    "Daniel Berger",
    "Akshay Bhatia",
    "Keegan Bradley",
    "Michael Brennan",
    "Jacob Bridgeman",
    "Sam Burns",
    "Angel Cabrera",
    "Brian Campbell",
    "Patrick Cantlay",
    "Wyndham Clark",
    "Corey Conners",
    "Fred Couples",
    "Jason Day",
    "Bryson DeChambeau",
    "Nicolas Echavarria",
    "Harris English",
    "Matt Fitzpatrick",
    "Tommy Fleetwood",
    "Ryan Fox",
    "Sergio Garcia",
    "Ryan Gerard",
    "Chris Gotterup",
    "Max Greyserman",
    "Ben Griffin",
    "Harry Hall",
    "Brian Harman",
    "Tyrrell Hatton",
    "Russell Henley",
    "Nicolai Hojgaard",
    "Rasmus Hojgaard",
    "Max Homa",
    "Viktor Hovland",
    "Sungjae Im",
    "Casey Jarvis",
    "Dustin Johnson",
    "Zach Johnson",
    "Si Woo Kim",
    "Michael Kim",
    "Kurt Kitayama",
    "Jake Knapp",
    "Brooks Koepka",
    "Min Woo Lee",
    "Haotong Li",
    "Shane Lowry",
    "Robert MacIntyre",
    "Hideki Matsuyama",
    "Matt McCarty",
    "Rory McIlroy",
    "Tom McKibbin",
    "Maverick McNealy",
    "Phil Mickelson",
    "Collin Morikawa",
    "Rasmus Neergaard-Petersen",
    "Alex Noren",
    "Andrew Novak",
    "Carlos Ortiz",
    "Marco Penge",
    "Aldrich Potgieter",
    "Jon Rahm",
    "Aaron Rai",
    "Patrick Reed",
    "Kristoffer Reitan",
    "Davis Riley",
    "Justin Rose",
    "Xander Schauffele",
    "Scottie Scheffler",
    "Charl Schwartzel",
    "Adam Scott",
    "Vijay Singh",
    "Cameron Smith",
    "J.J. Spaun",
    "Jordan Spieth",
    "Samuel Stevens",
    "Sepp Straka",
    "Nick Taylor",
    "Justin Thomas",
    "Sami Valimaki",
    "Bubba Watson",
    "Mike Weir",
    "Danny Willett",
    "Gary Woodland",
    "Tiger Woods",
    "Cameron Young",
]

# Amateurs — tracked separately, not typically in DataGolf player DB
MASTERS_AMATEURS_2026 = [
    "Ethan Fang",
    "Jackson Herrington",
    "Brandon Holtz",
    "Mason Howell",
    "Naoyuki Kataoka",
    "John Keefer",
    "Fifa Laopakdee",
    "Mateo Pulcini",
    "José María Olazábal",
    "Samuel Stevens",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MASTERS_EVENT_NAME = "The Masters"
MASTERS_COURSE = "Augusta National Golf Club"
MASTERS_START = date(2026, 4, 9)
MASTERS_END = date(2026, 4, 12)

POOL_CODE = "rvcc-masters-2026"
POOL_NAME = "RVCC Masters Pool 2026"
CLUB_CODE = "rvcc"

RVCC_RULES_JSON = {
    "variant": "rvcc",
    "pick_count": 7,
    "count_best": 5,
    "min_cuts_to_qualify": 5,
    "uses_buckets": False,
    # Auto-activate: pool transitions to live + scoring_enabled at this time.
    # 2 PM EDT = 18:00 UTC (April is EDT, UTC-4)
    "scoring_starts_at": "2026-04-09T18:00:00+00:00",
}

ENTRY_OPEN_AT = "2026-04-01T00:00:00+00:00"
# Lock entries before first tee time Thursday morning.
# 8 AM EDT = 12:00 UTC
ENTRY_DEADLINE = "2026-04-09T12:00:00+00:00"

# Synthetic dg_id range for manually-added players not in DataGolf.
# Real DataGolf IDs are positive ints (typically 1–30000+).
# We use 900_000+ to avoid collision.  When DataGolf later syncs the
# field, their entries upsert by (tournament_id, dg_id) — our synthetic
# entries stay alongside, and any player DG knows gets real scoring data.
_SYNTHETIC_DG_ID_START = 900_000


# ---------------------------------------------------------------------------
# Name matching helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------


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


def find_or_create_masters_tournament(session, *, dry_run: bool = False) -> int:
    """Find The Masters 2026 or create it. Returns tournament id."""
    # Try to find existing
    row = session.execute(
        text("""
            SELECT id, event_name, start_date, status
            FROM golf_tournaments
            WHERE (LOWER(event_name) LIKE '%masters%' OR LOWER(event_name) LIKE '%augusta%')
              AND start_date >= '2026-04-01' AND start_date <= '2026-04-15'
            ORDER BY start_date
            LIMIT 1
        """)
    ).fetchone()

    if row:
        print(f"  Found existing tournament: {row[1]} (id={row[0]}, status={row[3]})")
        return row[0]

    # Also try by event_id if DataGolf has synced it with a different name
    row = session.execute(
        text("""
            SELECT id, event_name, start_date, status
            FROM golf_tournaments
            WHERE tour = 'pga'
              AND start_date >= '2026-04-01' AND start_date <= '2026-04-15'
            ORDER BY start_date
            LIMIT 1
        """)
    ).fetchone()

    if row:
        print(f"  Found tournament by date: {row[1]} (id={row[0]}, status={row[3]})")
        return row[0]

    if dry_run:
        print("  [DRY RUN] Would create The Masters tournament")
        return -1

    # Create it
    result = session.execute(
        text("""
            INSERT INTO golf_tournaments
                (event_id, tour, event_name, course, course_key,
                 start_date, end_date, season, status, created_at, updated_at)
            VALUES
                (:event_id, 'pga', :event_name, :course, :course_key,
                 :start_date, :end_date, 2026, 'scheduled', NOW(), NOW())
            ON CONFLICT ON CONSTRAINT uq_golf_tournament_event_tour DO UPDATE SET
                event_name = EXCLUDED.event_name,
                course = EXCLUDED.course,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "event_id": "014",  # DataGolf Masters event_id
            "event_name": MASTERS_EVENT_NAME,
            "course": MASTERS_COURSE,
            "course_key": "augusta_national",
            "start_date": MASTERS_START,
            "end_date": MASTERS_END,
        },
    )
    tid = result.fetchone()[0]
    session.commit()
    print(f"  Created tournament: {MASTERS_EVENT_NAME} (id={tid})")
    return tid


def insert_field(session, tournament_id: int, matched: list[dict], *, dry_run: bool = False) -> int:
    """Insert matched players into golf_tournament_fields."""
    if dry_run:
        print(f"  [DRY RUN] Would insert {len(matched)} field entries")
        return 0

    sql = text("""
        INSERT INTO golf_tournament_fields
            (tournament_id, dg_id, player_name, status, updated_at)
        VALUES
            (:tournament_id, :dg_id, :player_name, 'active', NOW())
        ON CONFLICT ON CONSTRAINT uq_golf_field_entry DO UPDATE SET
            player_name = EXCLUDED.player_name,
            status = EXCLUDED.status,
            updated_at = NOW()
    """)

    count = 0
    for m in matched:
        session.execute(sql, {
            "tournament_id": tournament_id,
            "dg_id": m["dg_id"],
            "player_name": m["dg_name"],
        })
        count += 1

    session.commit()
    return count


def create_pool(session, tournament_id: int, *, status: str = "draft", dry_run: bool = False) -> int:
    """Create the RVCC Masters pool. Returns pool id."""
    # Check for existing
    row = session.execute(
        text("""
            SELECT id, status FROM golf_pools
            WHERE tournament_id = :tid AND club_code = :club
            LIMIT 1
        """),
        {"tid": tournament_id, "club": CLUB_CODE},
    ).fetchone()

    if row:
        print(f"  Pool already exists (id={row[0]}, status={row[1]})")
        return row[0]

    if dry_run:
        print(f"  [DRY RUN] Would create pool '{POOL_NAME}' with status='{status}'")
        return -1

    result = session.execute(
        text("""
            INSERT INTO golf_pools
                (code, name, club_code, tournament_id, status, rules_json,
                 entry_open_at, entry_deadline, max_entries_per_email,
                 scoring_enabled, require_upload, allow_self_service_entry,
                 notes, created_at, updated_at)
            VALUES
                (:code, :name, :club_code, :tournament_id, :status,
                 CAST(:rules_json AS jsonb),
                 CAST(:entry_open_at AS timestamptz), CAST(:entry_deadline AS timestamptz),
                 :max_entries_per_email,
                 FALSE, FALSE, TRUE,
                 :notes, NOW(), NOW())
            RETURNING id
        """),
        {
            "code": POOL_CODE,
            "name": POOL_NAME,
            "club_code": CLUB_CODE,
            "tournament_id": tournament_id,
            "status": status,
            "rules_json": json.dumps(RVCC_RULES_JSON),
            "entry_open_at": ENTRY_OPEN_AT,
            "entry_deadline": ENTRY_DEADLINE,
            "max_entries_per_email": 3,
            "notes": (
                "RVCC Masters Pool 2026. "
                "Pick 7 golfers, best 5 scores count. "
                "Min 5 must make the cut to qualify. "
                "Lowest aggregate wins."
            ),
        },
    )
    pool_id = result.fetchone()[0]
    session.commit()
    return pool_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Set up RVCC Masters 2026 pool")
    parser.add_argument("--open", action="store_true", help="Set pool to 'open' (accepting entries)")
    parser.add_argument("--field-only", action="store_true", help="Just show field mapping results")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument(
        "--other",
        type=str,
        default="",
        help="Comma-separated extra player names to add (e.g. --other 'Luke Donald, Zach Blair')",
    )
    args = parser.parse_args()

    # Build full field: hardcoded list + amateurs + --other additions
    all_field = list(MASTERS_FIELD_2026)
    for n in MASTERS_AMATEURS_2026:
        if n not in all_field:
            all_field.append(n)

    if args.other:
        for name in args.other.split(","):
            name = name.strip()
            if name and name not in all_field:
                all_field.append(name)
                print(f"  Added via --other: {name}")

    # Step 1: Load player catalog and match names
    print("\n[1] Matching field to DataGolf player IDs...")
    with get_session() as session:
        player_index = load_all_players(session)

    print(f"  Loaded {len(player_index)} player name variants from golf_players")
    matched, unmatched = match_field_to_players(all_field, player_index)
    print(f"  Matched: {len(matched)} / {len(all_field)}")

    # Step 2: Create golf_players entries for unmatched (amateurs, --other, etc.)
    newly_created: list[dict] = []
    if unmatched:
        print(f"\n[2] Creating {len(unmatched)} unmatched players with synthetic dg_ids...")
        for name in unmatched:
            tag = " (A)" if name in MASTERS_AMATEURS_2026 else ""
            print(f"    + {name}{tag}")
        with get_session() as session:
            newly_created = create_unmatched_players(session, unmatched, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"  Created {len(newly_created)} player entries (dg_id {_SYNTHETIC_DG_ID_START}+)")
    else:
        print("\n[2] All players matched — no synthetic entries needed")

    # Combine matched + newly created for the full field
    full_field = matched + newly_created

    # Print full field mapping
    print(f"\n  {'#':<4} {'Field Name':<35} {'DG Name':<30} {'DG ID':<8} {'Source':<10}")
    print(f"  {'-'*4} {'-'*35} {'-'*30} {'-'*8} {'-'*10}")
    for i, m in enumerate(sorted(full_field, key=lambda x: x["field_name"]), 1):
        amateur = " (A)" if m.get("amateur") else ""
        source = "synthetic" if m["dg_id"] >= _SYNTHETIC_DG_ID_START else "datagolf"
        print(f"  {i:<4} {m['field_name'] + amateur:<35} {m['dg_name']:<30} {m['dg_id']:<8} {source:<10}")

    print(f"\n  Total field: {len(full_field)} players")

    if args.field_only:
        return

    # Step 3: Find or create The Masters tournament
    print("\n[3] Finding/creating The Masters 2026 tournament...")
    with get_session() as session:
        tournament_id = find_or_create_masters_tournament(session, dry_run=args.dry_run)

    if tournament_id < 0:
        return

    # Step 4: Insert full field (matched + newly created)
    print(f"\n[4] Inserting {len(full_field)} players into tournament field...")
    with get_session() as session:
        count = insert_field(session, tournament_id, full_field, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"  Upserted {count} field entries")

    # Step 5: Create pool
    initial_status = "open" if args.open else "draft"
    print(f"\n[5] Creating RVCC pool (status='{initial_status}')...")
    with get_session() as session:
        pool_id = create_pool(session, tournament_id, status=initial_status, dry_run=args.dry_run)

    if pool_id < 0:
        return

    # If --open and pool already existed, update status
    if args.open and not args.dry_run:
        with get_session() as session:
            session.execute(
                text("""
                    UPDATE golf_pools SET status = 'open', updated_at = NOW()
                    WHERE id = :id AND status != 'open'
                """),
                {"id": pool_id},
            )
            session.commit()

    # Summary
    dg_count = len([m for m in full_field if m["dg_id"] < _SYNTHETIC_DG_ID_START])
    syn_count = len([m for m in full_field if m["dg_id"] >= _SYNTHETIC_DG_ID_START])

    print(f"\n{'='*60}")
    print(" RVCC Masters Pool 2026 - Setup Complete")
    print(f"{'='*60}")
    print(f"  Tournament ID:    {tournament_id}")
    print(f"  Pool ID:          {pool_id}")
    print(f"  Field size:       {len(full_field)} players")
    print(f"    DataGolf-matched: {dg_count}")
    print(f"    Synthetic IDs:    {syn_count} (amateurs / --other)")
    print(f"  Entry opens:      April 1, 2026")
    print(f"  Entry deadline:   April 9, 2026 at 8:00 AM ET")
    print(f"  Status:           {initial_status}")
    print()
    print("  RVCC Rules:")
    print("    - Pick any 7 golfers from the field")
    print("    - At least 5 must make the cut to qualify")
    print("    - Best 5 scores count toward your total")
    print("    - If 6-7 make the cut, worst 1-2 are dropped")
    print("    - Lowest aggregate score wins")
    print()
    print("  Lifecycle (auto-managed):")
    print(f"    Now         -> status='open', entries accepted")
    print(f"    Apr 9 8a ET -> auto-locked (entry_deadline passed)")
    print(f"    Apr 9 2p ET -> auto-activated (scoring_starts_at in rules_json)")
    print(f"                   status='live', scoring_enabled=true")
    print(f"    Apr 12      -> PATCH /api/golf/pools/{pool_id} {{status: 'final'}}")
    print()
    print("  Frontend endpoints:")
    print(f"    GET  /api/golf/pools/{pool_id}/field          -- pick from these players")
    print(f"    POST /api/golf/pools/{pool_id}/entries        -- submit 7 picks")
    print(f"    GET  /api/golf/pools/{pool_id}/leaderboard    -- live standings")
    print(f"    GET  /api/golf/pools/{pool_id}/entries/by-email?email=x -- lookup picks")
    print()
    print("  DataGolf reconciliation:")
    print("    When DataGolf publishes the Masters field, sync_field will add")
    print("    entries by real dg_id alongside synthetic ones. Players with")
    print("    real dg_ids get live leaderboard scoring automatically.")
    print("    Synthetic-ID players show as 'unknown' until reconciled.")
    print()
    print("  Auto-running (Celery beat, already configured):")
    print("    - Field sync:       every 6 hours (will pick up DG field)")
    print("    - Leaderboard sync: every 5 min (DataGolf)")
    print("    - Pool scoring:     every 5 min (when status='live')")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
