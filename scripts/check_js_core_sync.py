#!/usr/bin/env python3
"""CI gate: verify packages/js-core/ TS types cover all /api/v1/ response fields.

Strategy:
1. Boot FastAPI, dump OpenAPI schema.
2. Collect all property names from schemas reachable from /api/v1/ response bodies
   (follows $refs recursively, once per schema to avoid cycles).
3. Parse packages/js-core/src/**/*.ts for all property names in type/interface definitions.
4. Fail if any API schema property name is absent from all js-core type definitions.

Exit 0 on success, 1 on violations.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"
JS_CORE_SRC = REPO_ROOT / "packages" / "js-core" / "src"
sys.path.insert(0, str(API_DIR))

REF_PREFIX = "#/components/schemas/"

# Match property names in TS interface/type literal definitions.
# Handles: `  name: T`, `  name?: T`, `  readonly name: T`, `  "quoted-key": T`
# Requires ≥2 leading spaces so top-level import/export statements are skipped.
_TS_PROP_RE = re.compile(
    r"""(?m)^\s{2,}(?:readonly\s+)?(?:"([^"]+)"|([a-zA-Z_$][a-zA-Z0-9_$]*))\s*\??:""",
)


def _load_app() -> Any:
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    from main import app  # type: ignore[import]

    return app


def _collect_schema_fields(
    obj: Any,
    fields: set[str],
    seen_refs: set[str],
    all_schemas: dict[str, Any],
) -> None:
    """Recursively collect property names from an OpenAPI schema object."""
    if not isinstance(obj, dict):
        return

    ref = obj.get("$ref", "")
    if ref.startswith(REF_PREFIX):
        schema_name = ref[len(REF_PREFIX):]
        if schema_name not in seen_refs:
            seen_refs.add(schema_name)
            _collect_schema_fields(
                all_schemas.get(schema_name, {}), fields, seen_refs, all_schemas
            )
        return

    for key, value in obj.get("properties", {}).items():
        fields.add(key)
        _collect_schema_fields(value, fields, seen_refs, all_schemas)

    for combiner in ("allOf", "anyOf", "oneOf"):
        for sub in obj.get(combiner, []):
            _collect_schema_fields(sub, fields, seen_refs, all_schemas)

    if "items" in obj:
        _collect_schema_fields(obj["items"], fields, seen_refs, all_schemas)

    if isinstance(obj.get("additionalProperties"), dict):
        _collect_schema_fields(
            obj["additionalProperties"], fields, seen_refs, all_schemas
        )


def _collect_v1_fields(openapi: dict[str, Any]) -> set[str]:
    """Return all property names from /api/v1/ response schemas."""
    all_schemas = openapi.get("components", {}).get("schemas", {})
    fields: set[str] = set()
    seen_refs: set[str] = set()

    for path, path_item in openapi.get("paths", {}).items():
        if not path.startswith("/api/v1/"):
            continue
        if not isinstance(path_item, dict):
            continue
        for method, method_item in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(method_item, dict):
                continue
            for response in method_item.get("responses", {}).values():
                if not isinstance(response, dict):
                    continue
                for media_obj in response.get("content", {}).values():
                    if isinstance(media_obj, dict):
                        _collect_schema_fields(
                            media_obj.get("schema", {}),
                            fields,
                            seen_refs,
                            all_schemas,
                        )

    return fields


def _collect_ts_fields(ts_dir: Path) -> set[str]:
    """Parse all .ts files under ts_dir and return all object property names."""
    fields: set[str] = set()
    for ts_file in ts_dir.rglob("*.ts"):
        text = ts_file.read_text(encoding="utf-8")
        for match in _TS_PROP_RE.finditer(text):
            name = match.group(1) or match.group(2)
            if name:
                fields.add(name)
    return fields


def main() -> int:
    app = _load_app()
    openapi = app.openapi()

    v1_path_count = sum(
        1 for p in openapi.get("paths", {}) if p.startswith("/api/v1/")
    )
    print(f"OpenAPI paths scanned: {len(openapi.get('paths', {}))}")
    print(f"  /api/v1/ paths: {v1_path_count}")

    api_fields = _collect_v1_fields(openapi)
    ts_fields = _collect_ts_fields(JS_CORE_SRC)

    print(f"  /api/v1/ response property names: {len(api_fields)}")
    print(f"packages/js-core/ TS property names: {len(ts_fields)}")

    missing = sorted(api_fields - ts_fields)

    if missing:
        print(
            f"\nERROR: {len(missing)} /api/v1/ response field(s) absent from packages/js-core/:\n"
        )
        for field in missing:
            print(f"  {field}")
        print(
            "\nUpdate packages/js-core/src/ to include these fields, "
            "then re-run this check."
        )
        return 1

    print("OK: all /api/v1/ response fields are covered by packages/js-core/ types.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
