#!/usr/bin/env python3
"""Lint Pydantic response models for missing camelCase aliases.

A model PASSES if:
  - Its model_config contains an alias_generator, OR
  - All snake_case fields (name contains '_') have Field(alias=...) annotations

A model is SKIPPED if its class name ends with any SKIP_SUFFIXES.

Exit 0 on success, 1 if violations found.
"""

import ast
import sys
from pathlib import Path

SKIP_SUFFIXES = (
    "Request",
    "Config",
    "Settings",
    "Base",
    "Mixin",
    "Enum",
    "Filter",
    "Filters",
    "Payload",
    "Input",
    "Slot",
    "Action",
)

# Direct Pydantic base classes that mark a class as a model to lint.
PYDANTIC_BASES = {"BaseModel", "BaseSettings", "CamelResponse"}

# Base classes that imply alias_generator on all subclasses (inherited config).
ALIAS_GENERATOR_BASES = {"CamelResponse"}


def _has_underscore(name: str) -> bool:
    return "_" in name and not name.startswith("_")


def _to_camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _model_has_alias_generator(
    class_node: ast.ClassDef, alias_cfg_names: set[str]
) -> bool:
    """Return True if the class has alias_generator coverage.

    Coverage is present when:
    - The class body assigns model_config with alias_generator, OR
    - The class directly inherits from a base that implies alias_generator
      (e.g. CamelResponse), meaning all subclasses inherit the config.
    """
    # Inherited alias_generator via known base class
    for base in class_node.bases:
        base_name = ast.unparse(base).split(".")[-1]
        if base_name in ALIAS_GENERATOR_BASES:
            return True

    for item in class_node.body:
        if not isinstance(item, ast.Assign):
            continue
        for target in item.targets:
            if not (isinstance(target, ast.Name) and target.id == "model_config"):
                continue
            value = item.value
            if isinstance(value, ast.Call):
                for kw in value.keywords:
                    if kw.arg == "alias_generator":
                        return True
            # Also handle plain dict literal: model_config = {"alias_generator": ...}
            if isinstance(value, ast.Dict):
                for k in value.keys:
                    if isinstance(k, ast.Constant) and k.value == "alias_generator":
                        return True
            # Handle pre-computed variable: _ALIAS_CFG = ConfigDict(alias_generator=...)
            if isinstance(value, ast.Name) and value.id in alias_cfg_names:
                return True
    return False


def _field_has_alias(ann_assign: ast.AnnAssign) -> bool:
    """Return True if the annotated assignment calls Field(alias=...)."""
    if ann_assign.value is None:
        return False
    if not isinstance(ann_assign.value, ast.Call):
        return False
    for kw in ann_assign.value.keywords:
        if kw.arg == "alias":
            return True
    return False


def _is_pydantic_model(class_node: ast.ClassDef) -> bool:
    for base in class_node.bases:
        name = ast.unparse(base)
        if any(b in name for b in PYDANTIC_BASES):
            return True
    return False


def _collect_alias_cfg_names(module_tree: ast.Module) -> set[str]:
    """Collect module-level variable names assigned ConfigDict(alias_generator=...)."""
    names: set[str] = set()
    for node in ast.walk(module_tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg == "alias_generator":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                break
    return names


def check_file(path: Path) -> list[tuple[str, str, str]]:
    """Return list of (model_name, field_name, suggested_alias) violations."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    # Collect names of module-level variables that are ConfigDict(alias_generator=...)
    alias_cfg_names = _collect_alias_cfg_names(tree)

    violations: list[tuple[str, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Skip non-response models
        if any(node.name.endswith(s) for s in SKIP_SUFFIXES):
            continue

        if not _is_pydantic_model(node):
            continue

        if _model_has_alias_generator(node, alias_cfg_names):
            continue

        # Check each annotated field
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            field_name = item.target.id
            if not _has_underscore(field_name):
                continue
            if not _field_has_alias(item):
                violations.append((node.name, field_name, _to_camel(field_name)))

    return violations


def main() -> int:
    repo_root = Path(__file__).parent.parent
    api_app_dir = repo_root / "api" / "app"

    if not api_app_dir.is_dir():
        print(f"ERROR: {api_app_dir} not found", file=sys.stderr)
        return 1

    all_violations: list[tuple[str, str, str, str]] = []
    for py_file in sorted(api_app_dir.rglob("*.py")):
        for model_name, field_name, alias in check_file(py_file):
            rel = str(py_file.relative_to(repo_root))
            all_violations.append((rel, model_name, field_name, alias))

    if all_violations:
        print(
            "ERROR: snake_case fields missing camelCase alias in Pydantic response models:\n"
        )
        for file_path, model, field, alias in all_violations:
            print(
                f"  {file_path}:  {model}.{field}"
                f"  →  needs Field(alias='{alias}') or alias_generator=to_camel"
            )
        print(
            f"\n{len(all_violations)} violation(s) found. "
            "Add model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True) "
            "to each response model, or add Field(alias='camelCase') to each snake_case field."
        )
        return 1

    print(f"OK: all Pydantic response models in {api_app_dir} have camelCase aliases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
