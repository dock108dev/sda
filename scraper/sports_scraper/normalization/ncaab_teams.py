"""NCAAB team abbreviation dictionary — Single Source of Truth.

Contains canonical team names, abbreviations, and CBB API IDs for all 358
Division I men's basketball programs. Abbreviations are sourced from CBS/ESPN
broadcast standards and manually curated for uniqueness (zero collisions).

This module is the authoritative source for NCAAB team normalization.
"""

from __future__ import annotations

# (canonical_name, abbreviation, cbb_team_id)
# Sorted alphabetically by canonical name.
from .ncaab_teams_data import _NCAAB_TEAM_DATA
# Primary lookup: canonical_name -> (canonical_name, abbreviation)
NCAAB_TEAM_ABBREVIATIONS: dict[str, tuple[str, str]] = {
    name: (name, abbr) for name, abbr, _cbb_id in _NCAAB_TEAM_DATA
}

# Reverse lookup: abbreviation -> canonical_name
NCAAB_ABBREV_TO_NAME: dict[str, str] = {
    abbr: name for name, abbr, _cbb_id in _NCAAB_TEAM_DATA
}

# CBB team ID -> (canonical_name, abbreviation)
NCAAB_CBB_ID_TO_TEAM: dict[int, tuple[str, str]] = {
    cbb_id: (name, abbr) for name, abbr, cbb_id in _NCAAB_TEAM_DATA
}

# Variation lookup: common alternate names -> (canonical_name, abbreviation)
# Built programmatically from the team data.
NCAAB_VARIATIONS: dict[str, tuple[str, str]] = {}


def _name_to_seo(name: str) -> str:
    """Convert a canonical team name to NCAA seo format.

    NCAA API returns team names in lowercase-hyphenated format without mascot,
    e.g. "Michigan St Spartans" -> "michigan-st", "North Carolina Tar Heels" -> "north-carolina".
    """
    # Strip mascot (last word) — same as the "school without mascot" logic
    parts = name.rsplit(" ", 1)
    school = parts[0] if len(parts) > 1 else name
    return school.lower().replace(" ", "-").replace("'", "").replace(".", "")


def _build_variations() -> None:
    """Build variation lookup from team data.

    Generates lookup entries for:
    - Full canonical name (exact)
    - Lowercase canonical name
    - Abbreviation (e.g., "DUKE" -> Duke Blue Devils)
    - School name without mascot (last word stripped)
    - NCAA seo format (lowercase-hyphenated, e.g., "michigan-st")
    - Common short forms for well-known programs
    """
    for name, abbr, _cbb_id in _NCAAB_TEAM_DATA:
        # Full name
        NCAAB_VARIATIONS[name] = (name, abbr)
        NCAAB_VARIATIONS[name.lower()] = (name, abbr)

        # Abbreviation
        NCAAB_VARIATIONS[abbr] = (name, abbr)
        NCAAB_VARIATIONS[abbr.lower()] = (name, abbr)

        # School name without mascot (strip last word)
        parts = name.rsplit(" ", 1)
        if len(parts) > 1:
            school = parts[0]
            NCAAB_VARIATIONS[school] = (name, abbr)
            NCAAB_VARIATIONS[school.lower()] = (name, abbr)
            # NCAA API adds trailing period to abbreviations (e.g., "Michigan St.")
            if school.endswith(" St") or school.endswith(" Univ"):
                NCAAB_VARIATIONS[school + "."] = (name, abbr)
                NCAAB_VARIATIONS[(school + ".").lower()] = (name, abbr)

        # NCAA seo format (e.g., "michigan-st", "north-carolina")
        seo = _name_to_seo(name)
        if seo and seo not in NCAAB_VARIATIONS:
            NCAAB_VARIATIONS[seo] = (name, abbr)

        # For teams with "State" in their name, add "St"/"St." short forms
        # so NCAA API names like "Ohio St." resolve correctly.
        # Handles both "Ohio State Buckeyes" (State in name) and multi-word
        # mascots like "Penn State Nittany Lions" or "Kent State Golden Flashes".
        state_idx = name.find(" State ")
        if state_idx != -1:
            # e.g., "Ohio State Buckeyes" → prefix = "Ohio"
            prefix = name[:state_idx]
            # "Ohio St" / "Ohio St."
            for suffix in ["St", "St."]:
                variant = f"{prefix} {suffix}"
                NCAAB_VARIATIONS[variant] = (name, abbr)
                NCAAB_VARIATIONS[variant.lower()] = (name, abbr)
            # "Penn State" (for multi-word mascots where school != "X State")
            state_variant = f"{prefix} State"
            if state_variant not in NCAAB_VARIATIONS:
                NCAAB_VARIATIONS[state_variant] = (name, abbr)
                NCAAB_VARIATIONS[state_variant.lower()] = (name, abbr)
            # SEO variant: "ohio-st"
            st_seo = f"{prefix.lower().replace(' ', '-')}-st"
            if st_seo not in NCAAB_VARIATIONS:
                NCAAB_VARIATIONS[st_seo] = (name, abbr)

        # For "St" teams (canonical already abbreviated, e.g., "Michigan St Spartans"),
        # add truncated short form ("Michigan St", "Michigan St.") and
        # "State" full form ("Michigan State").
        st_idx = name.find(" St ")
        if st_idx != -1:
            prefix = name[:st_idx]
            # "Michigan St" / "Michigan St."
            for suffix in ["St", "St."]:
                variant = f"{prefix} {suffix}"
                NCAAB_VARIATIONS[variant] = (name, abbr)
                NCAAB_VARIATIONS[variant.lower()] = (name, abbr)
            # "Michigan State"
            state_variant = f"{prefix} State"
            if state_variant not in NCAAB_VARIATIONS:
                NCAAB_VARIATIONS[state_variant] = (name, abbr)
                NCAAB_VARIATIONS[state_variant.lower()] = (name, abbr)

    # Manual well-known variations
    _WELL_KNOWN: dict[str, str] = {
        # Common short names
        "Bama": "Alabama Crimson Tide",
        "Zona": "Arizona Wildcats",
        "Hogs": "Arkansas Razorbacks",
        "Cougars": "BYU Cougars",  # ambiguous but BYU most common
        "Bears": "Baylor Bears",
        "Zags": "Gonzaga Bulldogs",
        "Hoosiers": "Indiana Hoosiers",
        "Jayhawks": "Kansas Jayhawks",
        "Rock Chalk": "Kansas Jayhawks",
        "Wildcats": "Kentucky Wildcats",
        "Cards": "Louisville Cardinals",
        "Terps": "Maryland Terrapins",
        "Spartans": "Michigan St Spartans",
        "Tar Heels": "North Carolina Tar Heels",
        "Heels": "North Carolina Tar Heels",
        "Carolina": "North Carolina Tar Heels",
        "Buckeyes": "Ohio State Buckeyes",
        "Sooners": "Oklahoma Sooners",
        "Boilermakers": "Purdue Boilermakers",
        "Orange": "Syracuse Orange",
        "Vols": "Tennessee Volunteers",
        "Longhorns": "Texas Longhorns",
        "Huskies": "UConn Huskies",
        "Wahoos": "Virginia Cavaliers",
        "Hokies": "Virginia Tech Hokies",
        "Deacs": "Wake Forest Demon Deacons",
        "Mountaineers": "West Virginia Mountaineers",
        "Badgers": "Wisconsin Badgers",
        # Alternate full names
        "North Carolina": "North Carolina Tar Heels",
        "NC State": "NC State Wolfpack",
        "Kentucky": "Kentucky Wildcats",
        "Duke": "Duke Blue Devils",
        "Kansas": "Kansas Jayhawks",
        "Indiana": "Indiana Hoosiers",
        "UConn": "UConn Huskies",
        "Gonzaga": "Gonzaga Bulldogs",
        "Villanova": "Villanova Wildcats",
        "Virginia": "Virginia Cavaliers",
        "Purdue": "Purdue Boilermakers",
        "Michigan State": "Michigan St Spartans",
        "Ohio State": "Ohio State Buckeyes",
        "Florida State": "Florida St Seminoles",
        "Iowa State": "Iowa State Cyclones",
        "Kansas State": "Kansas St Wildcats",
        "Michigan": "Michigan Wolverines",
        "Tennessee": "Tennessee Volunteers",
        "Alabama": "Alabama Crimson Tide",
        "Auburn": "Auburn Tigers",
        "Florida": "Florida Gators",
        "Arizona": "Arizona Wildcats",
        "Arizona State": "Arizona St Sun Devils",
        "Baylor": "Baylor Bears",
        "Texas": "Texas Longhorns",
        "Texas Tech": "Texas Tech Red Raiders",
        "Oklahoma": "Oklahoma Sooners",
        "Oklahoma State": "Oklahoma St Cowboys",
        "Oregon": "Oregon Ducks",
        "Wisconsin": "Wisconsin Badgers",
        "Marquette": "Marquette Golden Eagles",
        "Creighton": "Creighton Bluejays",
        "Louisville": "Louisville Cardinals",
        "Stanford": "Stanford Cardinal",
        "Notre Dame": "Notre Dame Fighting Irish",
        "Georgetown": "Georgetown Hoyas",
        "Connecticut": "UConn Huskies",
        "Maryland": "Maryland Terrapins",
        "Pittsburgh": "Pittsburgh Panthers",
        "Syracuse": "Syracuse Orange",
        "Cincinnati": "Cincinnati Bearcats",
        "Memphis": "Memphis Tigers",
        "Houston": "Houston Cougars",
        "SMU": "SMU Mustangs",
        "TCU": "TCU Horned Frogs",
        "West Virginia": "West Virginia Mountaineers",
        "Colorado": "Colorado Buffaloes",
        "Utah": "Utah Utes",
        "BYU": "BYU Cougars",
        "Arkansas": "Arkansas Razorbacks",
        "Missouri": "Missouri Tigers",
        "Mississippi State": "Mississippi St Bulldogs",
        "Ole Miss": "Ole Miss Rebels",
        "LSU": "LSU Tigers",
        "Clemson": "Clemson Tigers",
        "Wake Forest": "Wake Forest Demon Deacons",
        "Georgia Tech": "Georgia Tech Yellow Jackets",
        "Georgia": "Georgia Bulldogs",
        "South Carolina": "South Carolina Gamecocks",
        "Vanderbilt": "Vanderbilt Commodores",
        "Xavier": "Xavier Musketeers",
        "San Diego State": "San Diego St Aztecs",
        "Dayton": "Dayton Flyers",
        "St. John's": "St. John's Red Storm",
        "St John's": "St. John's Red Storm",
        "Providence": "Providence Friars",
        "Seton Hall": "Seton Hall Pirates",
        "UNLV": "UNLV Rebels",
        "Nevada": "Nevada Wolf Pack",
        "UCLA": "UCLA Bruins",
        "USC": "USC Trojans",
        "Southern California": "USC Trojans",
        "Southern California Trojans": "USC Trojans",
        # HBCU / mid-major names that collide after normalization
        "Alabama A&M": "Alabama A&M Bulldogs",
        "Alabama A&M Bulldogs": "Alabama A&M Bulldogs",
        "Coppin State": "Coppin St Eagles",
        "Coppin St": "Coppin St Eagles",
        "Coppin State Eagles": "Coppin St Eagles",
        "Grambling": "Grambling St Tigers",
        "Grambling State": "Grambling St Tigers",
        "Grambling St": "Grambling St Tigers",
        "Grambling Tigers": "Grambling St Tigers",
        "Grambling State Tigers": "Grambling St Tigers",
        "Howard": "Howard Bison",
        "Howard Bison": "Howard Bison",
        "Maryland Eastern Shore": "Maryland-Eastern Shore Hawks",
        "Maryland-Eastern Shore": "Maryland-Eastern Shore Hawks",
        "UMES": "Maryland-Eastern Shore Hawks",
        "North Carolina Central": "North Carolina Central Eagles",
        "NC Central": "North Carolina Central Eagles",
        "North Carolina Central Eagles": "North Carolina Central Eagles",
        "Texas Southern": "Texas Southern Tigers",
        "Texas Southern Tigers": "Texas Southern Tigers",
        # NCAA API short name abbreviations — the NCAA scoreboard uses
        # abbreviated state prefixes (Fla., N., S., W., E.) and drops mascots.
        # Multi-word mascots (Mean Green, Tar Heels, Golden Eagles, etc.)
        # break rsplit-based stripping, so explicit mappings are required.
        "Boston U.": "Boston University",
        "Boston U": "Boston University",
        "Boston Univ. Terriers": "Boston University",
        "Boston Univ.": "Boston University",
        "Northern Ky.": "Northern Kentucky Norse",
        "Northern Ky": "Northern Kentucky Norse",
        # Florida -> Fla.
        "Fla. Atlantic": "Florida Atlantic Owls",
        "Fla. Gulf Coast": "Florida Gulf Coast Eagles",
        "Fla. A&M": "Florida A&M Rattlers",
        "Fla. International": "Florida Int'l Golden Panthers",
        "Fla. State": "Florida St Seminoles",
        "Fla. St.": "Florida St Seminoles",
        # Multi-word mascot teams (school name without mascot)
        "North Texas": "North Texas Mean Green",
        "Southern Miss": "Southern Miss Golden Eagles",
        "South Carolina Upstate": "South Carolina Upstate Spartans",
        "Southern Indiana": "Southern Indiana Screaming Eagles",
        "Fort Wayne": "Fort Wayne Mastodons",
        "Purdue Fort Wayne": "Fort Wayne Mastodons",
        # North/South/East/West abbreviated
        "N. Texas": "North Texas Mean Green",
        "N. Carolina": "North Carolina Tar Heels",
        "N. Carolina A&T": "North Carolina A&T Aggies",
        "N. Carolina Central": "North Carolina Central Eagles",
        "N. Alabama": "North Alabama Lions",
        "N. Florida": "North Florida Ospreys",
        "N. Dakota St.": "North Dakota St Bison",
        "N. Dakota": "North Dakota Fighting Hawks",
        "N. Arizona": "Northern Arizona Lumberjacks",
        "N. Illinois": "Northern Illinois Huskies",
        "N. Iowa": "Northern Iowa Panthers",
        "S. Carolina": "South Carolina Gamecocks",
        "S. Carolina St.": "South Carolina St Bulldogs",
        "S. Florida": "South Florida Bulls",
        "S. Alabama": "South Alabama Jaguars",
        "S. Dakota St.": "South Dakota St Jackrabbits",
        "S. Dakota": "South Dakota Coyotes",
        "S. Illinois": "Southern Illinois Salukis",
        "Southern Ill.": "Southern Illinois Salukis",
        "S. Miss": "Southern Miss Golden Eagles",
        "S. Utah": "Southern Utah Thunderbirds",
        "W. Virginia": "West Virginia Mountaineers",
        "W. Kentucky": "Western Kentucky Hilltoppers",
        "W. Michigan": "Western Michigan Broncos",
        "W. Carolina": "Western Carolina Catamounts",
        "W. Illinois": "Western Illinois Leathernecks",
        "E. Carolina": "East Carolina Pirates",
        "E. Michigan": "Eastern Michigan Eagles",
        "E. Kentucky": "Eastern Kentucky Colonels",
        "E. Washington": "Eastern Washington Eagles",
        "E. Illinois": "Eastern Illinois Panthers",
        "E. Tennessee St.": "East Tennessee St Buccaneers",
        "Detroit Mercy": "Detroit Mercy Titans",
        # NCAA scoreboard abbreviated names (different from S./N./E./W. pattern)
        "Eastern Ill.": "Eastern Illinois Panthers",
        "Ga. Southern": "Georgia Southern Eagles",
        "Middle Tenn.": "Middle Tennessee Blue Raiders",
        "Mississippi Val.": "Miss Valley St Delta Devils",
        "N.C. Central": "North Carolina Central Eagles",
        "South Fla.": "South Florida Bulls",
        "Southeast Mo. St.": "SE Missouri St Redhawks",
        "Southern Miss.": "Southern Miss Golden Eagles",
        "Southern U.": "Southern Jaguars",
        "Western Ky.": "Western Kentucky Hilltoppers",
        "Ark.-Pine Bluff": "Arkansas-Pine Bluff Golden Lions",
        "LMU (CA)": "Loyola Marymount Lions",
        # Loyola schools — APIs often use full city name instead of abbreviation
        "Loyola Chicago": "Loyola (Chi) Ramblers",
        "Loyola Chicago Ramblers": "Loyola (Chi) Ramblers",
        "Loyola-Chicago": "Loyola (Chi) Ramblers",
        "Loyola-Chicago Ramblers": "Loyola (Chi) Ramblers",
        "Loyola (IL)": "Loyola (Chi) Ramblers",
        "Loyola IL": "Loyola (Chi) Ramblers",
        "Loyola Maryland": "Loyola (MD) Greyhounds",
        "Loyola Maryland Greyhounds": "Loyola (MD) Greyhounds",
        "Loyola-Maryland": "Loyola (MD) Greyhounds",
        "Loyola-Maryland Greyhounds": "Loyola (MD) Greyhounds",
        # Miami (OH) — APIs may send "Miami Ohio" or "Miami (Ohio)"
        "Miami Ohio": "Miami (OH) RedHawks",
        "Miami Ohio RedHawks": "Miami (OH) RedHawks",
        "Miami (Ohio)": "Miami (OH) RedHawks",
        "Miami (Ohio) RedHawks": "Miami (OH) RedHawks",
        # St. Francis (PA)
        "Saint Francis Pennsylvania": "St. Francis (PA) Red Flash",
        "St. Francis Pennsylvania": "St. Francis (PA) Red Flash",
        "St. Francis (PA)": "St. Francis (PA) Red Flash",
        "St. Thomas (MN)": "St. Thomas-Minnesota",
        "St. Thomas (MN) Tommies": "St. Thomas-Minnesota",
        "Prairie View": "Prairie View Panthers",
        "Alcorn": "Alcorn St Braves",
        "UNI": "Northern Iowa Panthers",
        "FIU": "Florida Int'l Golden Panthers",
        "CSUN": "CSU Northridge Matadors",
        "CSU Bakersfield": "CSU Bakersfield Roadrunners",
        "Long Beach St.": "Long Beach St 49ers",
        "Cal St. Fullerton": "CSU Fullerton Titans",
        "Kennesaw St.": "Kennesaw St Owls",
        "Jacksonville St.": "Jacksonville St Gamecocks",
        "Tarleton St.": "Tarleton State Texans",
        "Lindenwood": "Lindenwood Lions",
        # N./Northern — NCAA scoreboard may use either prefix
        "N. Colorado": "N Colorado Bears",
        "Northern Colo.": "N Colorado Bears",
        "Northern Colorado": "N Colorado Bears",
        # Alternate full names the NCAA API may send
        "Texas A&M-Corpus Christi": "Texas A&M-CC Islanders",
        "Texas A&M Corpus Christi": "Texas A&M-CC Islanders",
        "A&M-Corpus Christi": "Texas A&M-CC Islanders",
        # Queens (short form without "University")
        "Queens": "Queens University Royals",
        "Queens (NC)": "Queens University Royals",
        # Central Arkansas abbreviated
        "Central Ark.": "Central Arkansas Bears",
        "Cent. Arkansas": "Central Arkansas Bears",
        # San Jose without accent (NCAA API may send either)
        "San Jose St.": "San Jos\u00e9 St Spartans",
        "San Jose St": "San Jos\u00e9 St Spartans",
        "San Jose State": "San Jos\u00e9 St Spartans",
        "San José St.": "San Jos\u00e9 St Spartans",
        "San José State": "San Jos\u00e9 St Spartans",
        # Hawaii without special characters
        "Hawaii": "Hawai'i Rainbow Warriors",
        "Hawai'i": "Hawai'i Rainbow Warriors",
        "Hawaii Rainbow Warriors": "Hawai'i Rainbow Warriors",
        # UT Arlington without hyphen
        "UT Arlington": "UT-Arlington Mavericks",
        "UTA": "UT-Arlington Mavericks",
        # Eastern Washington abbreviated
        "Eastern Wash.": "Eastern Washington Eagles",
        "E. Wash.": "Eastern Washington Eagles",
        # East Tennessee abbreviated
        "East Tenn. St.": "East Tennessee St Buccaneers",
        "E. Tenn. St.": "East Tennessee St Buccaneers",
        # Cal Baptist abbreviated
        "Cal Bapt.": "Cal Baptist Lancers",
        "California Baptist": "Cal Baptist Lancers",
        # Illinois (prevent fuzzy mismatch to Northern Illinois)
        "Illinois": "Illinois Fighting Illini",
        # North Dakota (prevent fuzzy mismatch to North Dakota St)
        "North Dakota": "North Dakota Fighting Hawks",
        # Sam Houston — NCAA scoreboard returns "Sam Houston" without "St"
        # which fuzzy-matches to "Houston Cougars" instead of Sam Houston St
        "Sam Houston": "Sam Houston St Bearkats",
        "Sam Houston State": "Sam Houston St Bearkats",
        # George Washington — NCAA scoreboard returns "George Washington"
        # which fuzzy-matches to "Washington Huskies" instead of GW
        "George Washington": "GW Revolutionaries",
        "George Washington Colonials": "GW Revolutionaries",
    }

    for variation, canonical in _WELL_KNOWN.items():
        if canonical in NCAAB_TEAM_ABBREVIATIONS:
            _, abbr = NCAAB_TEAM_ABBREVIATIONS[canonical]
            NCAAB_VARIATIONS[variation] = (canonical, abbr)
            NCAAB_VARIATIONS[variation.lower()] = (canonical, abbr)


_build_variations()

# Sanity check: all abbreviations are unique
assert len(NCAAB_ABBREV_TO_NAME) == len(_NCAAB_TEAM_DATA), (
    f"Duplicate abbreviations detected! "
    f"{len(_NCAAB_TEAM_DATA)} teams but {len(NCAAB_ABBREV_TO_NAME)} unique abbreviations"
)
