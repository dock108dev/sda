"""Static field and pool config for RVCC Masters 2026 setup."""

from __future__ import annotations

from datetime import date

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
