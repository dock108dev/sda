#!/usr/bin/env python3
"""CI gate: ensure all /api/v1/ response fields are camelCase in the OpenAPI schema.

Boots the FastAPI app, dumps the OpenAPI schema via app.openapi(), then:
  1. Collects all schemas reachable from /api/v1/ response bodies (follows $refs).
  2. Walks every property key in those schemas.
  3. Fails (exit 1) if any property key matches the snake_case pattern [a-z]_[a-z].

Admin endpoints (/api/admin/) are excluded.

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
sys.path.insert(0, str(API_DIR))

SNAKE_RE = re.compile(r"[a-z]_[a-z]")
REF_PREFIX = "#/components/schemas/"


def _is_snake(key: str) -> bool:
    return bool(SNAKE_RE.search(key))


def _load_app():
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
    )
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    from main import app  # type: ignore

    return app


def _walk_violations(
    obj: Any,
    path: str,
    violations: list[str],
    seen_refs: set[str],
    all_schemas: dict[str, Any],
) -> None:
    """Recursively walk an OpenAPI schema object, collecting snake_case property keys.

    Follows $ref pointers once each (tracked in seen_refs) to avoid cycles.
    Only checks keys inside ``properties`` dicts — not OpenAPI meta-keys.
    """
    if not isinstance(obj, dict):
        return

    ref = obj.get("$ref", "")
    if ref.startswith(REF_PREFIX):
        schema_name = ref[len(REF_PREFIX):]
        if schema_name not in seen_refs:
            seen_refs.add(schema_name)
            resolved = all_schemas.get(schema_name, {})
            _walk_violations(
                resolved,
                f"components/schemas/{schema_name}",
                violations,
                seen_refs,
                all_schemas,
            )
        return

    for key, value in obj.get("properties", {}).items():
        prop_path = f"{path}.properties.{key}"
        if _is_snake(key):
            violations.append(prop_path)
        _walk_violations(value, prop_path, violations, seen_refs, all_schemas)

    for combiner in ("allOf", "anyOf", "oneOf"):
        for i, sub in enumerate(obj.get(combiner, [])):
            _walk_violations(
                sub, f"{path}.{combiner}[{i}]", violations, seen_refs, all_schemas
            )

    if "items" in obj:
        _walk_violations(
            obj["items"], f"{path}.items", violations, seen_refs, all_schemas
        )

    if isinstance(obj.get("additionalProperties"), dict):
        _walk_violations(
            obj["additionalProperties"],
            f"{path}.additionalProperties",
            violations,
            seen_refs,
            all_schemas,
        )


def _check_v1_paths(openapi: dict[str, Any]) -> list[str]:
    """Return snake_case violation paths from all /api/v1/ response schemas."""
    all_schemas = openapi.get("components", {}).get("schemas", {})
    violations: list[str] = []
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

            for status_code, response in method_item.get("responses", {}).items():
                if not isinstance(response, dict):
                    continue
                content = response.get("content", {})
                for media_type, media_obj in content.items():
                    if not isinstance(media_obj, dict):
                        continue
                    schema = media_obj.get("schema", {})
                    base_path = (
                        f"paths.{path}.{method}.responses"
                        f".{status_code}.content.{media_type}.schema"
                    )
                    _walk_violations(
                        schema, base_path, violations, seen_refs, all_schemas
                    )

    return violations


def main() -> int:
    app = _load_app()
    openapi = app.openapi()

    v1_path_count = sum(
        1 for p in openapi.get("paths", {}) if p.startswith("/api/v1/")
    )
    print(f"OpenAPI paths scanned: {len(openapi.get('paths', {}))}")
    print(f"  /api/v1/ paths: {v1_path_count}")

    violations = _check_v1_paths(openapi)

    if violations:
        print(
            f"\nERROR: {len(violations)} snake_case field(s) found in /api/v1/ "
            "response schemas:\n"
        )
        for field_path in sorted(violations):
            print(f"  {field_path}")
        print(
            "\nAll /api/v1/ response fields must be camelCase. "
            "Add Field(alias='camelCaseName') to each snake_case field, "
            "or set alias_generator=to_camel in model_config."
        )
        return 1

    print("OK: no snake_case fields in /api/v1/ response schemas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
