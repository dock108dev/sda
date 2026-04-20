#!/usr/bin/env python3
"""Audit script: find JSONB columns used in ORM WHERE clauses and output a migration plan.

Scans Python source files for SQLAlchemy JSONB subscript access inside
.filter() / .where() calls (e.g. ``Model.col["key"].astext``).

Usage::

    python scripts/audit_jsonb_where_clauses.py [root_dir]

Outputs a Markdown-formatted migration plan to stdout.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class JsonbWhereUsage:
    file: str
    line: int
    model: str
    column: str
    key: str


@dataclass
class MigrationCandidate:
    model: str
    column: str
    keys: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class JsonbWhereVisitor(ast.NodeVisitor):
    """Walk an AST and collect Model.col["key"].astext usages.

    SQLAlchemy's .astext accessor is exclusively used in query expressions
    (filter/where/order_by), so any occurrence indicates a JSONB-queried field
    regardless of whether it appears inline or assigned to a local variable.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.usages: list[JsonbWhereUsage] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Match: (anything.)Model.col["key"].astext
        # Chain: Attribute(astext) → Subscript → Attribute(col) → Name/Attribute
        if node.attr == "astext" and isinstance(node.value, ast.Subscript):
            subscript = node.value
            col_attr = subscript.value
            if isinstance(col_attr, ast.Attribute):
                column_name = col_attr.attr
                model_name = _extract_name(col_attr.value)
                key = _extract_string(subscript.slice)
                if key is not None and model_name:
                    self.usages.append(
                        JsonbWhereUsage(
                            file=self.filename,
                            line=node.lineno,
                            model=model_name,
                            column=column_name,
                            key=key,
                        )
                    )

        self.generic_visit(node)


def _extract_string(node: ast.expr) -> str | None:
    """Return the string value of an AST node if it's a string constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_name(node: ast.expr) -> str | None:
    """Return the rightmost name component for Name or dotted Attribute chains."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ---------------------------------------------------------------------------
# File scanner
# ---------------------------------------------------------------------------


def scan_file(path: Path) -> list[JsonbWhereUsage]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, RecursionError):
        return []
    visitor = JsonbWhereVisitor(str(path))
    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(5000)
    try:
        visitor.visit(tree)
    except RecursionError:
        pass
    finally:
        sys.setrecursionlimit(old_limit)
    return visitor.usages


def scan_directory(root: Path) -> list[JsonbWhereUsage]:
    all_usages: list[JsonbWhereUsage] = []
    for py_file in sorted(root.rglob("*.py")):
        # Skip migrations, venv, __pycache__
        parts = py_file.parts
        if any(p in parts for p in ("alembic", "versions", "venv", ".venv", "__pycache__", "web", "node_modules")):
            continue
        all_usages.extend(scan_file(py_file))
    return all_usages


# ---------------------------------------------------------------------------
# Migration plan builder
# ---------------------------------------------------------------------------


def build_migration_plan(usages: list[JsonbWhereUsage]) -> list[MigrationCandidate]:
    candidates: dict[tuple[str, str], MigrationCandidate] = {}
    for u in usages:
        k = (u.model, u.column)
        if k not in candidates:
            candidates[k] = MigrationCandidate(model=u.model, column=u.column)
        cand = candidates[k]
        if u.key not in cand.keys:
            cand.keys.append(u.key)
        loc = f"{u.file}:{u.line}"
        if loc not in cand.locations:
            cand.locations.append(loc)
    return sorted(candidates.values(), key=lambda c: (c.model, c.column))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _print_report(candidates: list[MigrationCandidate], total_usages: int) -> None:
    print("# JSONB WHERE-Clause Audit Report\n")
    print(f"Total JSONB subscript usages inside filter/where: **{total_usages}**\n")

    if not candidates:
        print("No JSONB columns used in WHERE clauses detected.\n")
        return

    print(
        "The following JSONB columns are used in ORM WHERE clauses and are candidates "
        "for migration to typed columns:\n"
    )

    for cand in candidates:
        print(f"## `{cand.model}.{cand.column}`\n")
        print(f"**Keys queried:** {', '.join(f'`{k}`' for k in cand.keys)}\n")
        print("**Suggested migration:**")
        for key in cand.keys:
            col_type = "String(100)"
            print(f"  - Add `{key}: Mapped[str | None] = mapped_column({col_type}, nullable=True, index=True)`")
        print()
        print("**Query locations:**")
        for loc in cand.locations[:10]:
            print(f"  - `{loc}`")
        if len(cand.locations) > 10:
            print(f"  - ... and {len(cand.locations) - 10} more")
        print()
        print("**Migration steps:**")
        print("  1. Add typed column(s) to the ORM model")
        print("  2. Create Alembic migration (add column + backfill from JSONB)")
        print("  3. Update WHERE clauses to use the typed column")
        print("  4. Update write paths to populate both JSONB key and typed column")
        print(
            "  5. After soak period, remove JSONB key from write paths "
            "(keep in `external_ids` for legacy reads)"
        )
        print()

    print("## Already migrated\n")
    print(
        "- `SportsGame.external_ids[\"odds_api_event_id\"]` → "
        "`SportsGame.odds_api_event_id` (migration 20260419_000053)\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent
    usages = scan_directory(root)
    candidates = build_migration_plan(usages)
    _print_report(candidates, len(usages))


if __name__ == "__main__":
    main()
