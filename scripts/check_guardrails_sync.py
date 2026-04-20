#!/usr/bin/env python3
"""Check that guardrails.ts and validate_blocks.py / block_types.py share the
same block-type enumeration, required-role list, and numeric limits.

Canonical source of truth: the Python backend files.
Frontend guardrails.ts must mirror them.

Exit 0 = in sync.  Exit 1 = divergence detected (prints all mismatches).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]

BLOCK_TYPES_PY = ROOT / "api/app/services/pipeline/stages/block_types.py"
VALIDATE_BLOCKS_PY = ROOT / "api/app/services/pipeline/stages/validate_blocks.py"
GAME_FLOW_TYPES_TS = ROOT / "web/src/lib/api/sportsAdmin/gameFlowTypes.ts"
GUARDRAILS_TS = ROOT / "web/src/lib/guardrails.ts"


# ---------------------------------------------------------------------------
# Extractors — Python backend
# ---------------------------------------------------------------------------

def _extract_semantic_roles_py(path: Path) -> set[str]:
    """All SemanticRole enum values from block_types.py."""
    text = path.read_text()
    match = re.search(
        r'class SemanticRole\(.*?\):(.*?)(?=\n\nclass |\n@|\Z)',
        text,
        re.DOTALL,
    )
    if not match:
        return set()
    body = match.group(1)
    # Lines like:  SETUP = "SETUP"
    return set(re.findall(r'^\s+([A-Z_]+)\s*=\s*"([A-Z_]+)"', body, re.MULTILINE) and
               re.findall(r'"([A-Z_]+)"', body))


def _extract_required_roles_py(path: Path) -> set[str]:
    """Values from REQUIRED_BLOCK_TYPES frozenset in validate_blocks.py."""
    text = path.read_text()
    match = re.search(
        r'REQUIRED_BLOCK_TYPES\s*[:=].*?frozenset\(\[(.*?)\]\)',
        text,
        re.DOTALL,
    )
    if not match:
        return set()
    body = match.group(1)
    return set(re.findall(r'SemanticRole\.([A-Z_]+)\.value', body))


def _extract_int_constant_py(path: Path, name: str) -> int | None:
    """Extract a top-level integer constant by name."""
    text = path.read_text()
    m = re.search(rf'^{re.escape(name)}\s*=\s*(\d+)', text, re.MULTILINE)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Extractors — TypeScript frontend
# ---------------------------------------------------------------------------

def _extract_semantic_roles_ts(path: Path) -> set[str]:
    """All string literal values in the SemanticRole union type."""
    text = path.read_text()
    match = re.search(
        r'export\s+type\s+SemanticRole\s*=\s*((?:\s*\|\s*"[A-Z_]+")+)',
        text,
    )
    if not match:
        return set()
    return set(re.findall(r'"([A-Z_]+)"', match.group(1)))


def _extract_required_roles_ts(path: Path) -> set[str]:
    """Values from REQUIRED_BLOCK_TYPE_ROLES array in guardrails.ts."""
    text = path.read_text()
    # Skip the type annotation bracket (SemanticRole[]) by anchoring on '= ['
    match = re.search(
        r'REQUIRED_BLOCK_TYPE_ROLES\b.*?=\s*\[(.*?)\]',
        text,
        re.DOTALL,
    )
    if not match:
        return set()
    return set(re.findall(r'"([A-Z_]+)"', match.group(1)))


def _extract_int_constant_ts(path: Path, name: str) -> int | None:
    """Extract a top-level integer constant by name (literal only, not expressions)."""
    text = path.read_text()
    m = re.search(rf'export\s+const\s+{re.escape(name)}\s*=\s*(\d+)\s*;', text)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def main() -> int:
    errors: list[str] = []

    # ── 1. SemanticRole allowlist ────────────────────────────────────────────
    roles_py = _extract_semantic_roles_py(BLOCK_TYPES_PY)
    roles_ts = _extract_semantic_roles_ts(GAME_FLOW_TYPES_TS)

    if not roles_py:
        errors.append(f"Could not extract SemanticRole values from {BLOCK_TYPES_PY}")
    if not roles_ts:
        errors.append(f"Could not extract SemanticRole values from {GAME_FLOW_TYPES_TS}")

    if roles_py and roles_ts:
        only_py = roles_py - roles_ts
        only_ts = roles_ts - roles_py
        if only_py:
            errors.append(
                f"SemanticRole values in block_types.py but missing from gameFlowTypes.ts: {sorted(only_py)}"
            )
        if only_ts:
            errors.append(
                f"SemanticRole values in gameFlowTypes.ts but missing from block_types.py: {sorted(only_ts)}"
            )

    # ── 2. Required block types ──────────────────────────────────────────────
    req_py = _extract_required_roles_py(VALIDATE_BLOCKS_PY)
    req_ts = _extract_required_roles_ts(GUARDRAILS_TS)

    if not req_py:
        errors.append(f"Could not extract REQUIRED_BLOCK_TYPES from {VALIDATE_BLOCKS_PY}")
    if not req_ts:
        errors.append(f"Could not extract REQUIRED_BLOCK_TYPE_ROLES from {GUARDRAILS_TS}")

    if req_py and req_ts:
        only_req_py = req_py - req_ts
        only_req_ts = req_ts - req_py
        if only_req_py:
            errors.append(
                f"Required roles in validate_blocks.py but missing from guardrails.ts: {sorted(only_req_py)}"
            )
        if only_req_ts:
            errors.append(
                f"Required roles in guardrails.ts but missing from validate_blocks.py: {sorted(only_req_ts)}"
            )

    # ── 3. Numeric constants ─────────────────────────────────────────────────
    for const_name in ("MIN_BLOCKS", "MAX_BLOCKS", "MAX_TOTAL_WORDS"):
        py_val = _extract_int_constant_py(BLOCK_TYPES_PY, const_name)
        ts_val = _extract_int_constant_ts(GUARDRAILS_TS, const_name)

        if py_val is None:
            errors.append(f"Could not extract {const_name} from {BLOCK_TYPES_PY}")
        elif ts_val is None:
            errors.append(
                f"Could not extract {const_name} as a literal integer from {GUARDRAILS_TS} "
                f"(expected: {py_val}) — ensure it is a direct numeric literal, not a derived expression"
            )
        elif py_val != ts_val:
            errors.append(
                f"{const_name} mismatch: block_types.py={py_val}, guardrails.ts={ts_val}"
            )

    # ── Report ───────────────────────────────────────────────────────────────
    if errors:
        print("GUARDRAILS SYNC CHECK FAILED\n")
        for err in errors:
            print(f"  ✗ {err}")
        print(
            "\nFix: update web/src/lib/guardrails.ts to match the backend canonical values, "
            "then re-run this script."
        )
        return 1

    print("GUARDRAILS SYNC CHECK PASSED")
    print(f"  Block types    : {sorted(roles_py)}")
    print(f"  Required roles : {sorted(req_py)}")
    for c in ("MIN_BLOCKS", "MAX_BLOCKS", "MAX_TOTAL_WORDS"):
        val = _extract_int_constant_py(BLOCK_TYPES_PY, c)
        print(f"  {c:20s}: {val}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
