"""Constants for VALIDATE_BLOCKS (shared with tests and guardrail sync scripts)."""

from __future__ import annotations

from .block_types import SemanticRole

# Required semantic roles — every flow must contain at least these two block types.
# Mirrors REQUIRED_BLOCK_TYPE_ROLES in web/src/lib/guardrails.ts.
REQUIRED_BLOCK_TYPES: frozenset[str] = frozenset(
    [
        SemanticRole.SETUP.value,
        SemanticRole.RESOLUTION.value,
    ]
)

# Stat fields expected in every mini_box team stats dict.
MINI_BOX_STAT_FIELDS: frozenset[str] = frozenset(["points"])

# Sentinel for absent/unknown mini_box stat values — never null on the wire.
MINI_BOX_UNKNOWN = "UNKNOWN"

# Sentence count constraints
MIN_SENTENCES_PER_BLOCK = 1  # RESOLUTION blocks may be a single powerful sentence
MAX_SENTENCES_PER_BLOCK = 5  # DECISION_POINT blocks may need more detail

# Coverage validation
MAX_REGEN_ATTEMPTS = 2  # After 2 failed regen attempts, fall back to template

# Terms that indicate overtime in generated text; padded with spaces for word-boundary matching
OT_TERMS = frozenset(
    [
        "overtime",
        " ot ",
        "ot.",
        "ot,",
        "extra time",
        "sudden death",
        "double overtime",
        "triple overtime",
    ]
)

# Common abbreviations that contain periods but don't end sentences
COMMON_ABBREVIATIONS = [
    "Mr.",
    "Mrs.",
    "Ms.",
    "Dr.",
    "Jr.",
    "Sr.",
    "vs.",
    "etc.",
    "e.g.",
    "i.e.",
    "St.",
    "Ave.",
    "Blvd.",
    "Rd.",
    "Mt.",
    "Ft.",  # Addresses
    "Jan.",
    "Feb.",
    "Mar.",
    "Apr.",
    "Aug.",
    "Sept.",
    "Oct.",
    "Nov.",
    "Dec.",
]

# Final-window definitions per sport (see validate_blocks_resolution).
_FINAL_WINDOW_MIN_PERIOD: dict[str, int] = {
    "NHL": 3,
    "NCAAB": 2,
}
_CLOCK_SPORT_FINAL_QUARTER: dict[str, tuple[int, int]] = {
    "NBA": (4, 120),
    "NFL": (4, 120),
}
