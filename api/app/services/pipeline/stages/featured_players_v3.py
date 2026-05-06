"""V3 featured-player derivation.

Bridges the internal :class:`SegmentEvidence` (delta contribution from the
score timeline) and the v3 consumer schema's ``featured_players`` shape
({name, team, role, reason, stat_summary}). The ``reason`` string is the
key addition: it anchors each callout to the segment beat that earned the
mention so the consumer can't read "Bellinger had 2 RBI" as decoration.

Story-role-specific roles & reasons:

    opening             — skipped (no causal callouts; segment is setup).
    first_separation    — "opened the scoring" / "first lead-creating goal".
    response            — "led the response" / "answered with N {unit}".
    lead_change         — "took the lead with N {unit}".
    turning_point       — "powered the closing run" / "decided it with N {unit}".
    closeout            — "iced the game with N {unit}" — only when the
                          player actually scored inside the closeout block.
    blowout_compression — skipped (low-leverage padding).
"""

from __future__ import annotations

from typing import Any

from ..helpers.evidence_selection import FeaturedPlayer, SegmentEvidence

# Roles for which we surface up to two players. Lower volume than the
# `block_stars` mini-box list — featured_players exists to anchor the
# narrative beat, not to describe everyone who scored.
_FEATURED_ROLE_TOP_N: dict[str, int] = {
    "first_separation": 1,
    "response": 2,
    "lead_change": 1,
    "turning_point": 2,
    "closeout": 2,
}

# Roles that are skipped entirely — no featured_players entries emitted.
_SKIPPED_STORY_ROLES: frozenset[str] = frozenset(
    {"opening", "blowout_compression"}
)


def _scoring_unit(league_code: str) -> str:
    code = (league_code or "NBA").upper()
    if code == "MLB":
        return "runs"
    if code == "NHL":
        return "goals"
    return "points"


def _player_role_for_story(story_role: str, rank: int) -> str | None:
    """Map (story_role, rank) → the v3 ``FeaturedPlayer.role`` token.

    Pass 1's contract treats ``role`` as a free-form string; we use a small
    closed vocabulary so consumers can branch on it cleanly. ``rank`` is
    the player's 0-indexed position within the segment.
    """
    if story_role == "first_separation":
        return "first_separation_scorer"
    if story_role == "lead_change":
        return "lead_change_scorer"
    if story_role == "response":
        return "response_owner" if rank == 0 else "response_supporter"
    if story_role == "turning_point":
        return "run_owner" if rank == 0 else "run_supporter"
    if story_role == "closeout":
        return "late_closer" if rank == 0 else "closeout_supporter"
    return None


def _reason_for(
    story_role: str,
    player: FeaturedPlayer,
    league_code: str,
    rank: int,
    block: dict[str, Any] | None,
) -> str:
    """Produce a one-line, segment-causal reason string.

    Reasons reference real numbers (the player's segment delta_contribution)
    and the segment's story role, so they survive the validators in Pass 1
    (Rule 18) and the banned-phrase gate. They are intentionally short —
    the LLM render stage uses them as anchors, not as final prose.
    """
    unit = _scoring_unit(league_code)
    delta = max(int(player.delta_contribution), 0)

    if story_role == "first_separation":
        return f"Opened the scoring with {delta} {unit} in the segment."
    if story_role == "lead_change":
        return f"Lead-change {unit[:-1]} — segment delta {delta} {unit}."
    if story_role == "response":
        if rank == 0:
            return f"Led the response with {delta} {unit} in the segment."
        return f"Joined the response, adding {delta} {unit}."
    if story_role == "turning_point":
        if rank == 0:
            return f"Powered the deciding stretch with {delta} {unit}."
        return f"Supported the deciding stretch with {delta} {unit}."
    if story_role == "closeout":
        if rank == 0:
            return f"Iced the result with {delta} {unit} in the closing segment."
        return f"Added {delta} {unit} as the game closed."
    # Defensive fallback — never reached because _SKIPPED_STORY_ROLES gates
    # opening and blowout_compression upstream.
    return f"Contributed {delta} {unit} in the segment."


def _stat_summary(player: FeaturedPlayer, league_code: str) -> str:
    """Compact stat blurb derived from the segment delta contribution.

    Examples: "+11 pts (segment)", "+1 goal (segment)", "+2 runs (segment)".
    """
    delta = max(int(player.delta_contribution), 0)
    code = (league_code or "NBA").upper()
    if code == "MLB":
        unit = "run" if delta == 1 else "runs"
    elif code == "NHL":
        unit = "goal" if delta == 1 else "goals"
    else:
        unit = "pt" if delta == 1 else "pts"
    return f"+{delta} {unit} (segment)"


def derive_featured_players(
    block: dict[str, Any],
    evidence: SegmentEvidence | None,
    league_code: str,
) -> list[dict[str, Any]] | None:
    """Return the v3 ``featured_players`` payload for a block.

    Reads the block's ``story_role`` (populated by Pass 2's classifier) and
    derives causal player callouts from ``evidence.featured_players`` (the
    delta-contribution list selected per-segment by the existing evidence
    pipeline). Skipped story roles return ``None`` so the schema field stays
    null on opening / blowout_compression blocks.

    The output passes Rule 18 (every entry carries a non-empty ``reason``)
    by construction.
    """
    story_role = block.get("story_role")
    if not story_role or story_role in _SKIPPED_STORY_ROLES:
        return None
    if evidence is None or not evidence.featured_players:
        return None

    top_n = _FEATURED_ROLE_TOP_N.get(story_role, 1)
    selected = evidence.featured_players[:top_n]

    out: list[dict[str, Any]] = []
    for rank, player in enumerate(selected):
        if not player.name:
            continue
        out.append(
            {
                "name": player.name,
                "team": player.team,
                "role": _player_role_for_story(story_role, rank),
                "reason": _reason_for(
                    story_role, player, league_code, rank, block
                ),
                "stat_summary": _stat_summary(player, league_code),
            }
        )
    return out or None


def annotate_blocks_with_featured_players(
    blocks: list[dict[str, Any]],
    evidence_by_block: dict[int, SegmentEvidence],
    league_code: str,
) -> None:
    """Mutate each block dict to attach v3 ``featured_players``.

    Skipped story roles (opening, blowout_compression) leave the field
    untouched so the existing v2 ``mini_box.block_stars`` continues to
    decorate the consumer mini-box without crowding the narrative anchor.
    """
    for block in blocks:
        evidence = evidence_by_block.get(block.get("block_index"))
        derived = derive_featured_players(block, evidence, league_code)
        if derived is not None:
            block["featured_players"] = derived
