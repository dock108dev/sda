"""Deck-build pipeline.

Owns `build_deck_from_upstream` — the parity surface that fixture tests
call directly with a captured upstream payload — plus the validation
policy splitter and a deterministic source-hash for live-vs-official
deck-version stamping.

Pipeline order (matches the docstring on `service`):

    upstream payload
    → compute_timeline + compute_pitcher_timeline
    → select_plays + sample_tier_2
    → to_play_card + decorate_play_card (chip / narrative / leverage)
    → plan_deck (rhythm)
    → validate
    → apply_validation_policy
    → built_deck_to_dto
    → scan_response_for_final_score_leaks (re-runs policy)

The final-score-leak scan is deliberately at the end: it inspects the
serialized wire shape so the SSOT for what may leak is the schema, not
a hand-curated allowlist on the builder.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from ._dto import (
    built_deck_to_dto,
    decorate_play_card,
    scan_response_for_final_score_leaks,
)
from .deck_builder import build_scene_setter, select_plays, to_play_card
from .game_state import (
    compute_pitcher_stat_snapshots,
    compute_pitcher_timeline,
    compute_timeline,
    summarize_half_innings,
)
from .internal_types import BuiltPlayCard
from .rhythm_planner import plan_deck_with_report
from .schemas import (
    GenerationOutcome,
    GenerationPolicy,
    TeamSummary,
    ValidationSeverity,
    ValidationWarning,
)
from .validation import validate_no_duplicate_play_ids, validate_play_card

__all__ = [
    "apply_validation_policy",
    "build_deck_from_upstream",
    "generate_final_deck",
    "generate_live_deck",
]


# ---------------------------------------------------------------------------
# Validation severity policy
# ---------------------------------------------------------------------------


def apply_validation_policy(
    findings: Iterable[ValidationWarning], policy: GenerationPolicy
) -> tuple[list[ValidationWarning], list[ValidationWarning], bool]:
    """Split findings into (warnings, errors, blocked) per policy.

    `official` blocks on any error. `live` downgrades errors to warnings
    so an in-progress game never shows a blank screen for a transient
    contradiction in the upstream feed.
    """
    warnings: list[ValidationWarning] = []
    errors: list[ValidationWarning] = []
    for finding in findings:
        if finding.severity is ValidationSeverity.error:
            if policy is GenerationPolicy.official:
                errors.append(finding)
            else:
                warnings.append(
                    finding.model_copy(update={"severity": ValidationSeverity.warning})
                )
        else:
            warnings.append(finding)
    blocked = policy is GenerationPolicy.official and bool(errors)
    return warnings, errors, blocked


# ---------------------------------------------------------------------------
# Source hash
# ---------------------------------------------------------------------------


def _source_hash(payload: dict[str, Any]) -> str:
    """Stable signature of the inputs a deck was built from.

    Live polling uses this to decide whether the deck has actually
    changed:

      - gameId      (identity)
      - status      (live → final transitions force a new version)
      - playCount   (any new play forces a new version)
      - lastPlayIndex (covers re-orderings and back-fills)
      - homeScore / awayScore (covers backend score corrections that
        don't necessarily add a new play row)
      - lastPlayAt / lastIngestedAt (covers updates that fix data on
        existing plays — description corrections, runner attribution)

    These fields together give a deterministic-but-sensitive signature.
    Hash is truncated to 16 hex chars; collision risk is negligible for
    the keyspace (one game's lifetime).
    """
    game = payload.get("game") or {}
    plays = payload.get("plays") or []
    plays_sorted = sorted(plays, key=lambda p: p.get("playIndex", 0))
    last_idx = plays_sorted[-1].get("playIndex") if plays_sorted else None
    digest_input = {
        "gameId": game.get("id"),
        "status": game.get("status"),
        "playCount": len(plays),
        "lastPlayIndex": last_idx,
        "homeScore": game.get("homeScore"),
        "awayScore": game.get("awayScore"),
        "lastPlayAt": game.get("lastPlayAt"),
        "lastIngestedAt": game.get("lastIngestedAt"),
    }
    digest = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True).encode("utf-8")
    )
    return digest.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------


def build_deck_from_upstream(
    payload: dict[str, Any],
    *,
    policy: GenerationPolicy = GenerationPolicy.official,
    since_play_index: int | None = None,
) -> GenerationOutcome:
    """Build a Scroll Down MLB deck from an upstream game-detail payload.

    The payload shape mirrors the existing Next.js BFF: `{game, plays,
    mlbPitchers}`. For live polling, pass `since_play_index` to limit
    selected plays to those after the last one the client saw.
    """
    game = payload.get("game") or {}
    plays = list(payload.get("plays") or [])
    pitchers = payload.get("mlbPitchers")
    home_abbr = game.get("homeTeamAbbr")
    away_abbr = game.get("awayTeamAbbr")
    home_team = game.get("homeTeam", "Home")
    away_team = game.get("awayTeam", "Away")
    game_id = int(game.get("id") or 0)
    is_final = bool(game.get("isFinal")) or game.get("status") in (
        "final",
        "completed",
        "recap_ready",
        "archived",
    )

    # 1. Reconstruct game state across every play.
    timeline = compute_timeline(plays, home_abbr)
    pitcher_timeline = compute_pitcher_timeline(
        plays, pitchers, home_team, away_team, home_abbr
    )
    # Running stat snapshots per play — IP / K / BB / R / H / HR. Uses
    # `pitcher_timeline` as the per-play attribution source, so the line
    # always belongs to whoever was actually on the mound.
    pitcher_stats = compute_pitcher_stat_snapshots(plays, pitcher_timeline)

    # 2. Select plays.
    selected_ids, _reasons = select_plays(plays, timeline, game_id)

    # 3. Filter by `since` and sort.
    threshold = since_play_index if since_play_index is not None else -1
    selected_plays = sorted(
        [p for p in plays if int(p.get("playIndex", 0)) in selected_ids
         and int(p.get("playIndex", 0)) > threshold],
        key=lambda p: int(p.get("playIndex", 0)),
    )

    # 4. Assemble play cards.
    home_pp = game.get("homeProbablePitcher")
    away_pp = game.get("awayProbablePitcher")
    play_cards: list[BuiltPlayCard] = []
    for play in selected_plays:
        pid = int(play.get("playIndex", 0))
        frame = timeline.get(pid)
        if not frame:
            continue
        stat_snapshot = pitcher_stats.get(pid)
        card = to_play_card(
            game_id=game_id,
            sort_order=0,  # set by planner
            play=play,
            frame=frame,
            home_probable_pitcher=home_pp,
            away_probable_pitcher=away_pp,
            pitcher_of_record=pitcher_timeline.get(pid),
            pitcher_stat_line=stat_snapshot.format_compact() if stat_snapshot else None,
        )
        decorate_play_card(card)
        play_cards.append(card)

    # 5. Plan rhythm.
    half_meta = summarize_half_innings(timeline.values())
    venue = game.get("venueName") or game.get("venue") or game.get("location")
    scene = (
        build_scene_setter(
            game_id=game_id,
            home_team=home_team,
            away_team=away_team,
            home_team_abbr=home_abbr,
            away_team_abbr=away_abbr,
            game_date=game.get("gameDate", ""),
            home_probable_pitcher=home_pp,
            away_probable_pitcher=away_pp,
            venue=venue,
        )
        if since_play_index is None
        else None
    )
    deck, planner_report = plan_deck_with_report(
        scene=scene,
        play_cards=play_cards,
        half_inning_meta=half_meta,
        home_team_abbr=home_abbr or "HME",
        away_team_abbr=away_abbr or "AWY",
    )

    # 6. Validate.
    findings: list[ValidationWarning] = []
    for card in play_cards:
        findings.extend(validate_play_card(card))
    findings.extend(validate_no_duplicate_play_ids([c.play_index for c in play_cards]))

    warnings, errors, blocked = apply_validation_policy(findings, policy)

    deck_version = (
        f"official-{_source_hash(payload)}"
        if policy is GenerationPolicy.official
        else f"live-{_source_hash(payload)}"
    )

    if blocked:
        return GenerationOutcome(
            policy=policy,
            deck=None,
            warnings=warnings,
            errors=errors,
            blocked=True,
        )

    last_play_index = max(
        (int(p.get("playIndex", 0)) for p in plays), default=None
    )
    home_team_dto = TeamSummary(
        id=str(game.get("homeTeamId") or home_abbr or "home"),
        abbreviation=home_abbr or "HME",
        display_name=home_team,
        color_light=game.get("homeTeamColorLight"),
        color_dark=game.get("homeTeamColorDark"),
    )
    away_team_dto = TeamSummary(
        id=str(game.get("awayTeamId") or away_abbr or "away"),
        abbreviation=away_abbr or "AWY",
        display_name=away_team,
        color_light=game.get("awayTeamColorLight"),
        color_dark=game.get("awayTeamColorDark"),
    )

    response = built_deck_to_dto(
        game_id=game_id,
        deck=deck,
        planner_report_entries=planner_report.rhythm,
        validation_warnings=warnings,
        is_final=is_final,
        deck_version=deck_version,
        home_team=home_team_dto,
        away_team=away_team_dto,
        last_play_index=last_play_index,
        first_pitch=game.get("gameDate"),
        venue=venue,
        home_probable_pitcher=home_pp,
        away_probable_pitcher=away_pp,
    )

    # Final spoiler-safety guard: scan the serialized wire shape for any
    # forbidden final-score keys. Re-run policy so a leak in an `official`
    # deck blocks (and therefore is not persisted), instead of leaking
    # silently with a warning attached.
    leak_findings = scan_response_for_final_score_leaks(response)
    if leak_findings:
        warnings, errors, blocked = apply_validation_policy(
            findings + leak_findings, policy
        )
        if blocked:
            return GenerationOutcome(
                policy=policy,
                deck=None,
                warnings=warnings,
                errors=errors,
                blocked=True,
            )
        # Live policy: surface the leak finding alongside other warnings
        # but allow the deck through (matches the live/official split).
        response.validation_warnings = list(warnings)

    return GenerationOutcome(
        policy=policy,
        deck=response,
        warnings=warnings,
        errors=errors,
        blocked=False,
    )


async def generate_live_deck(payload: dict[str, Any]) -> GenerationOutcome:
    """Build a provisional deck from in-progress play data.

    Live policy: validation errors degrade to warnings — the user must not
    see a blank screen mid-game.
    """
    return build_deck_from_upstream(payload, policy=GenerationPolicy.live)


async def generate_final_deck(payload: dict[str, Any]) -> GenerationOutcome:
    """Build the official deck for a final game. Fails closed on validation
    errors so the canonical deck is never written from bad input."""
    return build_deck_from_upstream(payload, policy=GenerationPolicy.official)
