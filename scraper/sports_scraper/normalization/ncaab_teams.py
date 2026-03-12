"""NCAAB team abbreviation dictionary — Single Source of Truth.

Contains canonical team names, abbreviations, and CBB API IDs for all 358
Division I men's basketball programs. Abbreviations are sourced from CBS/ESPN
broadcast standards and manually curated for uniqueness (zero collisions).

This module is the authoritative source for NCAAB team normalization.
"""

from __future__ import annotations

# (canonical_name, abbreviation, cbb_team_id)
# Sorted alphabetically by canonical name.
_NCAAB_TEAM_DATA: list[tuple[str, str, int]] = [
    ("Abilene Christian Wildcats", "ACU", 1),
    ("Air Force Falcons", "AF", 2),
    ("Akron Zips", "AKR", 3),
    ("Alabama A&M Bulldogs", "AAMU", 4),
    ("Alabama Crimson Tide", "ALA", 5),
    ("Alabama St Hornets", "ALST", 6),
    ("Albany Great Danes", "ALB", 306),
    ("Alcorn St Braves", "ALC", 7),
    ("American Eagles", "AMER", 8),
    ("Appalachian St Mountaineers", "APP", 9),
    ("Arizona St Sun Devils", "ASU", 10),
    ("Arizona Wildcats", "ARIZ", 11),
    ("Arkansas Razorbacks", "ARK", 12),
    ("Arkansas St Red Wolves", "ARST", 13),
    ("Arkansas-Little Rock Trojans", "UALR", 144),
    ("Arkansas-Pine Bluff Golden Lions", "UAPB", 14),
    ("Army Knights", "ARMY", 15),
    ("Auburn Tigers", "AUB", 16),
    ("Austin Peay Governors", "APSU", 17),
    ("BYU Cougars", "BYU", 18),
    ("Ball State Cardinals", "BALL", 19),
    ("Baylor Bears", "BAY", 20),
    ("Bellarmine Knights", "BELL", 21),
    ("Belmont Bruins", "BELM", 22),
    ("Bethune-Cookman Wildcats", "BCU", 23),
    ("Binghamton Bearcats", "BING", 24),
    ("Boise State Broncos", "BSU", 25),
    ("Boston College Eagles", "BC", 26),
    ("Boston Univ. Terriers", "BU", 27),
    ("Bowling Green Falcons", "BGSU", 28),
    ("Bradley Braves", "BRAD", 29),
    ("Brown Bears", "BRWN", 30),
    ("Bryant Bulldogs", "BRY", 31),
    ("Bucknell Bison", "BUCK", 32),
    ("Buffalo Bulls", "BUFF", 33),
    ("Butler Bulldogs", "BUT", 34),
    ("CSU Bakersfield Roadrunners", "CSUB", 36),
    ("CSU Fullerton Titans", "CSUF", 37),
    ("CSU Northridge Matadors", "CSUN", 38),
    ("Cal Baptist Lancers", "CBU", 39),
    ("Cal Poly Mustangs", "CPOL", 35),
    ("California Golden Bears", "CAL", 40),
    ("Campbell Fighting Camels", "CAMP", 41),
    ("Canisius Golden Griffins", "CAN", 42),
    ("Central Arkansas Bears", "UCA", 43),
    ("Central Connecticut St Blue Devils", "CCSU", 44),
    ("Central Michigan Chippewas", "CMU", 45),
    ("Charleston Cougars", "COFC", 46),
    ("Charleston Southern Buccaneers", "CHSO", 47),
    ("Charlotte 49ers", "CLT", 48),
    ("Chattanooga Mocs", "CHAT", 49),
    ("Chicago St Cougars", "CHST", 50),
    ("Cincinnati Bearcats", "CIN", 51),
    ("Clemson Tigers", "CLEM", 52),
    ("Cleveland St Vikings", "CLEV", 53),
    ("Coastal Carolina Chanticleers", "CCU", 54),
    ("Colgate Raiders", "COLG", 55),
    ("Colorado Buffaloes", "COLO", 56),
    ("Colorado St Rams", "CSU", 57),
    ("Columbia Lions", "COLM", 58),
    ("Coppin St Eagles", "COPP", 59),
    ("Cornell Big Red", "COR", 60),
    ("Creighton Bluejays", "CREI", 61),
    ("Dartmouth Big Green", "DART", 62),
    ("Davidson Wildcats", "DAV", 63),
    ("Dayton Flyers", "DAY", 64),
    ("DePaul Blue Demons", "DEP", 65),
    ("Delaware Blue Hens", "DEL", 66),
    ("Delaware St Hornets", "DSU", 67),
    ("Denver Pioneers", "DEN", 68),
    ("Detroit Mercy Titans", "DET", 69),
    ("Drake Bulldogs", "DRKE", 70),
    ("Drexel Dragons", "DREX", 71),
    ("Duke Blue Devils", "DUKE", 72),
    ("Duquesne Dukes", "DUQ", 73),
    ("East Carolina Pirates", "ECU", 74),
    ("East Tennessee St Buccaneers", "ETSU", 75),
    ("East Texas A&M Lions", "ETAM", 76),
    ("Eastern Illinois Panthers", "EIU", 77),
    ("Eastern Kentucky Colonels", "EKU", 78),
    ("Eastern Michigan Eagles", "EMU", 79),
    ("Eastern Washington Eagles", "EWU", 80),
    ("Elon Phoenix", "ELON", 81),
    ("Evansville Purple Aces", "EVAN", 82),
    ("Fairfield Stags", "FAIR", 83),
    ("Fairleigh Dickinson Knights", "FDU", 84),
    ("Florida A&M Rattlers", "FAMU", 85),
    ("Florida Atlantic Owls", "FAU", 86),
    ("Florida Gators", "FLA", 87),
    ("Florida Gulf Coast Eagles", "FGCU", 88),
    ("Florida Int'l Golden Panthers", "FIU", 89),
    ("Florida St Seminoles", "FSU", 90),
    ("Fordham Rams", "FORD", 91),
    ("Fort Wayne Mastodons", "PFW", 237),
    ("Fresno St Bulldogs", "FRES", 92),
    ("Furman Paladins", "FUR", 93),
    ("GW Revolutionaries", "GW", 96),
    ("Gardner-Webb Bulldogs", "GWEB", 94),
    ("George Mason Patriots", "GMU", 95),
    ("Georgetown Hoyas", "GTWN", 97),
    ("Georgia Bulldogs", "UGA", 98),
    ("Georgia Southern Eagles", "GASO", 99),
    ("Georgia St Panthers", "GAST", 100),
    ("Georgia Tech Yellow Jackets", "GT", 101),
    ("Gonzaga Bulldogs", "GONZ", 102),
    ("Grambling St Tigers", "GRAM", 103),
    ("Grand Canyon Antelopes", "GCU", 104),
    ("Green Bay Phoenix", "GB", 105),
    ("Hampton Pirates", "HAMP", 106),
    ("Harvard Crimson", "HARV", 107),
    ("Hawai'i Rainbow Warriors", "HAW", 108),
    ("High Point Panthers", "HPU", 109),
    ("Hofstra Pride", "HOF", 110),
    ("Holy Cross Crusaders", "HC", 111),
    ("Houston Christian Huskies", "HCU", 112),
    ("Houston Cougars", "HOU", 113),
    ("Howard Bison", "HOW", 114),
    ("IUPUI Jaguars", "IUPU", 115),
    ("Idaho State Bengals", "IDST", 116),
    ("Idaho Vandals", "IDHO", 117),
    ("Illinois Fighting Illini", "ILL", 118),
    ("Illinois St Redbirds", "ILST", 119),
    ("Incarnate Word Cardinals", "UIW", 120),
    ("Indiana Hoosiers", "IND", 121),
    ("Indiana St Sycamores", "INST", 122),
    ("Iona Gaels", "IONA", 123),
    ("Iowa Hawkeyes", "IOWA", 124),
    ("Iowa State Cyclones", "ISU", 125),
    ("Jackson St Tigers", "JKST", 126),
    ("Jacksonville Dolphins", "JAX", 127),
    ("Jacksonville St Gamecocks", "JVST", 128),
    ("James Madison Dukes", "JMU", 129),
    ("Kansas Jayhawks", "KU", 131),
    ("Kansas St Wildcats", "KSU", 132),
    ("Kennesaw St Owls", "KENN", 133),
    ("Kent State Golden Flashes", "KENT", 134),
    ("Kentucky Wildcats", "UK", 135),
    ("LIU Sharks", "LIU", 146),
    ("LSU Tigers", "LSU", 136),
    ("La Salle Explorers", "LAS", 137),
    ("Lafayette Leopards", "LAF", 138),
    ("Lamar Cardinals", "LAM", 139),
    ("Le Moyne Dolphins", "LEM", 140),
    ("Lehigh Mountain Hawks", "LEH", 141),
    ("Liberty Flames", "LIB", 142),
    ("Lindenwood Lions", "LIND", 366),
    ("Lipscomb Bisons", "LIP", 143),
    ("Long Beach St 49ers", "LBSU", 145),
    ("Longwood Lancers", "LONG", 147),
    ("Louisiana Ragin' Cajuns", "ULL", 148),
    ("Louisiana Tech Bulldogs", "LT", 149),
    ("Louisville Cardinals", "LOU", 150),
    ("Loyola (Chi) Ramblers", "LOYC", 151),
    ("Loyola (MD) Greyhounds", "LOYM", 152),
    ("Loyola Marymount Lions", "LMU", 153),
    ("Maine Black Bears", "ME", 154),
    ("Manhattan Jaspers", "MANH", 155),
    ("Marist Red Foxes", "MRST", 156),
    ("Marquette Golden Eagles", "MARQ", 157),
    ("Marshall Thundering Herd", "MRSH", 158),
    ("Maryland-Eastern Shore Hawks", "UMES", 159),
    ("Maryland Terrapins", "MD", 160),
    ("Massachusetts Minutemen", "MASS", 161),
    ("McNeese Cowboys", "MCN", 162),
    ("Memphis Tigers", "MEM", 163),
    ("Mercer Bears", "MER", 164),
    ("Mercyhurst Lakers", "MERC", 165),
    ("Merrimack Warriors", "MERR", 166),
    ("Miami (OH) RedHawks", "MIOH", 167),
    ("Miami Hurricanes", "MIA", 168),
    ("Michigan St Spartans", "MSU", 169),
    ("Michigan Wolverines", "MICH", 170),
    ("Middle Tennessee Blue Raiders", "MTSU", 171),
    ("Milwaukee Panthers", "MKE", 172),
    ("Minnesota Golden Gophers", "MINN", 173),
    ("Miss Valley St Delta Devils", "MVSU", 175),
    ("Mississippi St Bulldogs", "MSST", 174),
    ("Missouri St Bears", "MOST", 176),
    ("Missouri Tigers", "MIZ", 177),
    ("Monmouth Hawks", "MON", 178),
    ("Montana Grizzlies", "MONT", 179),
    ("Montana St Bobcats", "MTST", 180),
    ("Morehead St Eagles", "MORE", 181),
    ("Morgan St Bears", "MORG", 182),
    ("Mt. St. Mary's Mountaineers", "MSM", 183),
    ("Murray St Racers", "MURR", 184),
    ("N Colorado Bears", "UNCO", 207),
    ("NC State Wolfpack", "NCST", 185),
    ("NJIT Highlanders", "NJIT", 186),
    ("Navy Midshipmen", "NAVY", 187),
    ("Nebraska Cornhuskers", "NEB", 188),
    ("Nevada Wolf Pack", "NEV", 189),
    ("New Hampshire Wildcats", "UNH", 190),
    ("New Haven Chargers", "NEWH", 1507),
    ("New Mexico Lobos", "UNM", 191),
    ("New Mexico St Aggies", "NMSU", 192),
    ("New Orleans Privateers", "UNO", 193),
    ("Niagara Purple Eagles", "NIAG", 194),
    ("Nicholls St Colonels", "NICH", 195),
    ("Norfolk St Spartans", "NORF", 196),
    ("North Alabama Lions", "UNA", 197),
    ("North Carolina A&T Aggies", "NCAT", 198),
    ("North Carolina Central Eagles", "NCCU", 199),
    ("North Carolina Tar Heels", "UNC", 200),
    ("North Dakota Fighting Hawks", "UND", 201),
    ("North Dakota St Bison", "NDSU", 202),
    ("North Florida Ospreys", "UNF", 203),
    ("North Texas Mean Green", "UNT", 204),
    ("Northeastern Huskies", "NEU", 205),
    ("Northern Arizona Lumberjacks", "NAU", 206),
    ("Northern Illinois Huskies", "NIU", 208),
    ("Northern Iowa Panthers", "UNI", 209),
    ("Northern Kentucky Norse", "NKU", 210),
    ("Northwestern St Demons", "NWST", 211),
    ("Northwestern Wildcats", "NW", 212),
    ("Notre Dame Fighting Irish", "ND", 213),
    ("Oakland Golden Grizzlies", "OAK", 214),
    ("Ohio Bobcats", "OHIO", 215),
    ("Ohio State Buckeyes", "OSU", 216),
    ("Oklahoma Sooners", "OU", 217),
    ("Oklahoma St Cowboys", "OKST", 218),
    ("Old Dominion Monarchs", "ODU", 219),
    ("Ole Miss Rebels", "MISS", 220),
    ("Omaha Mavericks", "OMA", 221),
    ("Oral Roberts Golden Eagles", "ORU", 222),
    ("Oregon Ducks", "ORE", 223),
    ("Oregon St Beavers", "ORST", 224),
    ("Pacific Tigers", "PAC", 225),
    ("Penn State Nittany Lions", "PSU", 226),
    ("Pennsylvania Quakers", "PENN", 227),
    ("Pepperdine Waves", "PEPP", 228),
    ("Pittsburgh Panthers", "PITT", 229),
    ("Portland Pilots", "PORT", 230),
    ("Portland St Vikings", "PRST", 231),
    ("Prairie View Panthers", "PVAM", 232),
    ("Presbyterian Blue Hose", "PRES", 233),
    ("Princeton Tigers", "PRIN", 234),
    ("Providence Friars", "PROV", 235),
    ("Purdue Boilermakers", "PUR", 236),
    ("Queens University Royals", "QU", 362),
    ("Quinnipiac Bobcats", "QUIN", 238),
    ("Radford Highlanders", "RAD", 239),
    ("Rhode Island Rams", "URI", 240),
    ("Rice Owls", "RICE", 241),
    ("Richmond Spiders", "RICH", 242),
    ("Rider Broncs", "RID", 243),
    ("Robert Morris Colonials", "RMU", 244),
    ("Rutgers Scarlet Knights", "RUT", 245),
    ("SE Louisiana Lions", "SELA", 246),
    ("SE Missouri St Redhawks", "SEMO", 272),
    ("SIU-Edwardsville Cougars", "SIUE", 247),
    ("SMU Mustangs", "SMU", 248),
    ("Sacramento St Hornets", "SAC", 249),
    ("Sacred Heart Pioneers", "SHU", 250),
    ("Saint Joseph's Hawks", "SJU", 251),
    ("Saint Louis Billikens", "SLU", 252),
    ("Saint Mary's Gaels", "SMC", 253),
    ("Saint Peter's Peacocks", "SPU", 254),
    ("Sam Houston St Bearkats", "SHSU", 255),
    ("Samford Bulldogs", "SAMF", 256),
    ("San Diego St Aztecs", "SDSU", 257),
    ("San Diego Toreros", "USD", 258),
    ("San Francisco Dons", "SF", 259),
    ("San Jos\u00e9 St Spartans", "SJSU", 260),
    ("Santa Clara Broncos", "SCU", 261),
    ("Seattle Redhawks", "SEA", 262),
    ("Seton Hall Pirates", "HALL", 263),
    ("Siena Saints", "SIEN", 264),
    ("South Alabama Jaguars", "USA", 265),
    ("South Carolina Gamecocks", "SC", 266),
    ("South Carolina St Bulldogs", "SCST", 267),
    ("South Carolina Upstate Spartans", "UPST", 268),
    ("South Dakota Coyotes", "SDAK", 269),
    ("South Dakota St Jackrabbits", "SDST", 270),
    ("South Florida Bulls", "USF", 271),
    ("Southern Illinois Salukis", "SIU", 273),
    ("Southern Indiana Screaming Eagles", "USI", 365),
    ("Southern Jaguars", "SOU", 274),
    ("Southern Miss Golden Eagles", "SMIS", 275),
    ("Southern Utah Thunderbirds", "SUU", 276),
    ("St. Bonaventure Bonnies", "SBU", 277),
    ("St. Francis (PA) Red Flash", "SFPA", 278),
    ("St. John's Red Storm", "SJN", 279),
    ("St. Thomas (MN) Tommies", "STMN", 280),
    ("Stanford Cardinal", "STAN", 281),
    ("Stephen F. Austin Lumberjacks", "SFA", 282),
    ("Stetson Hatters", "STET", 283),
    ("Stonehill Skyhawks", "STNH", 284),
    ("Stony Brook Seawolves", "STON", 285),
    ("Syracuse Orange", "SYR", 286),
    ("TCU Horned Frogs", "TCU", 287),
    ("Tarleton State Texans", "TARL", 288),
    ("Temple Owls", "TEM", 289),
    ("Tenn-Martin Skyhawks", "UTM", 325),
    ("Tennessee St Tigers", "TNST", 290),
    ("Tennessee Tech Golden Eagles", "TNTH", 291),
    ("Tennessee Volunteers", "TENN", 292),
    ("Texas A&M Aggies", "TAMU", 293),
    ("Texas A&M-CC Islanders", "TAMC", 294),
    ("Texas Longhorns", "TEX", 295),
    ("Texas Southern Tigers", "TXSO", 296),
    ("Texas State Bobcats", "TXST", 297),
    ("Texas Tech Red Raiders", "TTU", 298),
    ("The Citadel Bulldogs", "CIT", 299),
    ("Toledo Rockets", "TOL", 300),
    ("Towson Tigers", "TOW", 301),
    ("Troy Trojans", "TROY", 302),
    ("Tulane Green Wave", "TUL", 303),
    ("Tulsa Golden Hurricane", "TLSA", 304),
    ("UAB Blazers", "UAB", 305),
    ("UC Davis Aggies", "UCD", 307),
    ("UC Irvine Anteaters", "UCI", 308),
    ("UC Riverside Highlanders", "UCR", 309),
    ("UC San Diego Tritons", "UCSD", 310),
    ("UC Santa Barbara Gauchos", "UCSB", 311),
    ("UCF Knights", "UCF", 312),
    ("UCLA Bruins", "UCLA", 313),
    ("UConn Huskies", "CONN", 314),
    ("UIC Flames", "UIC", 315),
    ("UL Monroe Warhawks", "ULM", 316),
    ("UMBC Retrievers", "UMBC", 317),
    ("UMKC Kangaroos", "UMKC", 130),
    ("UMass Lowell River Hawks", "UMAL", 318),
    ("UNC Asheville Bulldogs", "UNCA", 319),
    ("UNC Greensboro Spartans", "UNCG", 320),
    ("UNC Wilmington Seahawks", "UNCW", 321),
    ("UNLV Rebels", "UNLV", 322),
    ("USC Trojans", "USC", 323),
    ("UT Rio Grande Valley Vaqueros", "UTRGV", 326),
    ("UT-Arlington Mavericks", "UTA", 324),
    ("UTEP Miners", "UTEP", 327),
    ("UTSA Roadrunners", "UTSA", 328),
    ("Utah State Aggies", "USU", 329),
    ("Utah Tech Trailblazers", "UTEC", 330),
    ("Utah Utes", "UTAH", 331),
    ("Utah Valley Wolverines", "UVU", 332),
    ("VCU Rams", "VCU", 333),
    ("VMI Keydets", "VMI", 334),
    ("Valparaiso Beacons", "VALP", 335),
    ("Vanderbilt Commodores", "VAN", 336),
    ("Vermont Catamounts", "UVM", 337),
    ("Villanova Wildcats", "NOVA", 338),
    ("Virginia Cavaliers", "UVA", 339),
    ("Virginia Tech Hokies", "VT", 340),
    ("Wagner Seahawks", "WAG", 341),
    ("Wake Forest Demon Deacons", "WAKE", 342),
    ("Washington Huskies", "WASH", 343),
    ("Washington St Cougars", "WSU", 344),
    ("Weber State Wildcats", "WEB", 345),
    ("West Georgia Wolves", "WGA", 346),
    ("West Virginia Mountaineers", "WVU", 347),
    ("Western Carolina Catamounts", "WCU", 348),
    ("Western Illinois Leathernecks", "WIU", 349),
    ("Western Kentucky Hilltoppers", "WKU", 350),
    ("Western Michigan Broncos", "WMU", 351),
    ("Wichita St Shockers", "WICH", 352),
    ("William & Mary Tribe", "WM", 353),
    ("Winthrop Eagles", "WIN", 354),
    ("Wisconsin Badgers", "WIS", 355),
    ("Wofford Terriers", "WOF", 356),
    ("Wright St Raiders", "WRST", 357),
    ("Wyoming Cowboys", "WYO", 358),
    ("Xavier Musketeers", "XAV", 359),
    ("Yale Bulldogs", "YALE", 360),
    ("Youngstown St Penguins", "YSU", 361),
]

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
        "Boston U.": "Boston Univ. Terriers",
        "Boston U": "Boston Univ. Terriers",
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
        "St. Thomas (MN)": "St. Thomas (MN) Tommies",
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
