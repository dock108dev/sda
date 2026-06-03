"""Team name normalization helpers for persistence."""

from __future__ import annotations

import re

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
