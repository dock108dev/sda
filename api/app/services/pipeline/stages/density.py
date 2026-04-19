"""Information density check: detect content-free flows that are template regurgitation.

Metric: Token Jaccard similarity between entity-stripped narrative and the
sport-specific fallback template. Jaccard is defined as:

    J(A, B) = |A ∩ B| / |A ∪ B|

where A = token set of entity-stripped generated narrative
      B = token set of entity-stripped sport template (rendered with placeholder names)

Jaccard was chosen because:
- Symmetric and bounded [0, 1]; easy to threshold per sport.
- Captures lexical overlap without sequence alignment or external NLP dependencies.
- At threshold ~0.60 it reliably flags template-regurgitation while leaving
  rich, entity-heavy narratives well below the limit.

A high score (≥ per-sport threshold) indicates that after removing entity-specific
tokens the generated text is nearly identical to the fallback template — meaning the
flow adds no information beyond what a deterministic render would produce.
"""
from __future__ import annotations

import logging
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_TOML_PATH = (
    Path(__file__).parents[5]
    / "scraper/sports_scraper/pipeline/grader_rules/generic_phrases.toml"
)

# Fallback if the TOML [density] section is absent or the file is missing.
_DEFAULT_THRESHOLD = 0.60


def _load_thresholds() -> tuple[float, dict[str, float]]:
    """Load per-sport Jaccard thresholds from the grader_rules TOML.

    Returns (default_threshold, {SPORT_UPPER: threshold, ...}).
    Falls back to _DEFAULT_THRESHOLD when the file or section is absent.
    """
    if not _TOML_PATH.exists():
        logger.warning("density_toml_not_found", extra={"path": str(_TOML_PATH)})
        return _DEFAULT_THRESHOLD, {}
    try:
        with open(_TOML_PATH, "rb") as fh:
            data = tomllib.load(fh)
        section = data.get("density", {})
        default = float(section.get("default", _DEFAULT_THRESHOLD))
        per_sport = {
            k.upper(): float(v) for k, v in section.items() if k != "default"
        }
        return default, per_sport
    except Exception:
        logger.warning(
            "density_toml_load_failed", exc_info=True, extra={"path": str(_TOML_PATH)}
        )
        return _DEFAULT_THRESHOLD, {}


_LOADED_DEFAULT, _SPORT_THRESHOLDS = _load_thresholds()


def _threshold_for(sport: str) -> float:
    return _SPORT_THRESHOLDS.get(sport.upper(), _LOADED_DEFAULT)


# ---------------------------------------------------------------------------
# Common English stopwords excluded from token comparison.
# Keeping only content words that capture game-action vocabulary.
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "their", "they", "it",
    "its", "this", "that", "these", "those", "into", "through", "during",
    "not", "after", "over", "under", "both", "each", "few", "more", "most",
    "other", "some", "such", "than", "too", "very", "just", "out", "about",
    "who", "which", "what", "while", "then", "when", "where", "there",
    "here", "all", "any", "also", "back", "between", "even", "him", "his",
    "how", "if", "me", "my", "now", "off", "our", "own", "put", "set",
    "so", "still", "them", "us", "use", "we", "your", "up",
])


# ---------------------------------------------------------------------------
# Entity stripping
# ---------------------------------------------------------------------------


def _strip_entities(text: str, known_names: list[str]) -> str:
    """Remove entity tokens from text to expose structural vocabulary.

    Strips in order:
    1. Score patterns (``107-98``, ``30 to 28``, en/em-dash variants).
    2. Known team/player name fragments supplied by the caller.
    3. Capitalized words (≥ 3 chars) — heuristic for proper nouns.
    4. Standalone digit sequences.
    """
    # 1. Score patterns
    text = re.sub(r"\b\d+\s*[-\u2013\u2014]\s*\d+\b", " ", text)
    text = re.sub(r"\b\d+\s+to\s+\d+\b", " ", text, flags=re.IGNORECASE)

    # 2. Known names (each space-split part stripped if > 2 chars)
    for name in known_names:
        for part in name.split():
            if len(part) > 2:
                text = re.sub(
                    rf"\b{re.escape(part)}\b", " ", text, flags=re.IGNORECASE
                )

    # 3. Capitalized words — proper nouns (player/team names not in known_names)
    text = re.sub(r"\b[A-Z][a-zA-Z]{2,}\b", " ", text)

    # 4. Standalone digit sequences
    text = re.sub(r"\b\d+\b", " ", text)

    return text


def _tokenize(text: str) -> frozenset[str]:
    """Return a frozenset of lowercase content words (≥ 3 chars, not stopwords)."""
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return frozenset(w for w in words if w not in _STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token Jaccard similarity: |A ∩ B| / |A ∪ B|, range [0.0, 1.0]."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# Template token cache
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _template_tokens(sport: str) -> frozenset[str]:
    """Return entity-stripped token set for the sport's fallback template.

    Rendered once with generic placeholder names so only structural vocabulary
    (not team/player names) enters the comparison. Cached per sport string.
    """
    from .templates import GameMiniBox, TemplateEngine  # local import avoids cycle

    mb = GameMiniBox(
        home_team="HomeTeam",
        away_team="AwayTeam",
        home_score=100,
        away_score=90,
        sport=sport,
        has_overtime=False,
        total_moments=8,
    )
    blocks = TemplateEngine.render(sport, mb)
    raw = " ".join(b.get("narrative", "") for b in blocks)
    stripped = _strip_entities(raw, ["HomeTeam", "AwayTeam"])
    return _tokenize(stripped)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_information_density(
    blocks: list[dict[str, Any]],
    sport: str,
    home_team: str = "",
    away_team: str = "",
) -> tuple[float, bool, list[str]]:
    """Check whether generated narrative is content-free template regurgitation.

    Strips entity tokens (team/player names, proper nouns, score patterns) from
    the concatenated block narratives and computes Token Jaccard similarity against
    the sport's deterministic fallback template. A high similarity score indicates
    the generated text adds no information beyond what the template would produce.

    Args:
        blocks:    Narrative blocks from the pipeline.
        sport:     Sport code (NBA, NFL, MLB, NHL, …).  Case-insensitive.
        home_team: Home team name for entity stripping (optional but recommended).
        away_team: Away team name for entity stripping (optional but recommended).

    Returns:
        ``(similarity_score, passed, warnings)``

        * **similarity_score** — 0.0 = fully distinct from template; 1.0 = identical.
        * **passed** — ``True`` when similarity < per-sport threshold.
        * **warnings** — Non-empty list (structured log-ready strings) when check fails.
          The check is always a soft signal; callers must not hard-reject on this alone.
    """
    sport_upper = sport.upper() if sport else "UNKNOWN"
    threshold = _threshold_for(sport_upper)

    raw_text = " ".join(b.get("narrative", "") for b in blocks if b.get("narrative"))
    if not raw_text.strip():
        return 0.0, True, []

    known_names = [n for n in [home_team, away_team] if n]
    stripped = _strip_entities(raw_text, known_names)
    narrative_tokens = _tokenize(stripped)

    if not narrative_tokens:
        return 0.0, True, []

    try:
        tmpl_tokens = _template_tokens(sport_upper)
    except Exception:
        logger.warning(
            "density_template_render_failed",
            exc_info=True,
            extra={"sport": sport_upper},
        )
        return 0.0, True, []

    score = _jaccard(narrative_tokens, tmpl_tokens)
    passed = score < threshold

    warnings: list[str] = []
    if not passed:
        msg = (
            f"Information density check failed: entity-stripped narrative has "
            f"{score:.2f} Jaccard similarity to the {sport_upper} template "
            f"(threshold={threshold:.2f}) — flow may be content-free template "
            f"regurgitation"
        )
        warnings.append(msg)
        logger.warning(
            "information_density_check_failed",
            extra={
                "sport": sport_upper,
                "jaccard_score": round(score, 4),
                "threshold": threshold,
                "narrative_token_count": len(narrative_tokens),
                "template_token_count": len(tmpl_tokens),
            },
        )

    return score, passed, warnings
