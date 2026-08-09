#!/usr/bin/env python3
"""Fail if GitHub workflows weaken the repository's maintenance-only boundary."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

CONFIRMATION = "DEPLOY SPORTS DATA ADMIN"
DEPLOYMENT_GATE = "maintenance-gate"
WORKFLOW_DIR = PurePosixPath(".github/workflows")
_SECRET_REF = re.compile(r"\$\{\{\s*secrets(?:\.|\[)")


class ActionsLoader(yaml.SafeLoader):
    """YAML 1.2-style loader that keeps the GitHub Actions `on` key intact."""


ActionsLoader.yaml_implicit_resolvers = {
    key: list(resolvers)
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for resolver_key, resolvers in ActionsLoader.yaml_implicit_resolvers.items():
    ActionsLoader.yaml_implicit_resolvers[resolver_key] = [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:bool"
    ]
ActionsLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def load_workflow_text(text: str, source: str) -> dict[str, Any]:
    """Parse one workflow and require a mapping at its root."""
    parsed = yaml.load(text, Loader=ActionsLoader)
    if not isinstance(parsed, dict):
        raise ValueError(f"{source}: workflow root must be a mapping")
    return parsed


def _walk_scalars(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _walk_scalars(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_scalars(child)
    elif value is not None:
        yield str(value)


def _event_names(workflow: Mapping[str, Any]) -> set[str]:
    triggers = workflow.get("on")
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, list):
        return {str(trigger) for trigger in triggers}
    if isinstance(triggers, Mapping):
        return {str(trigger) for trigger in triggers}
    return set()


def _is_false(value: Any) -> bool:
    return value is False or (isinstance(value, str) and value.lower() == "false")


def _needs_gate(job: Mapping[str, Any]) -> bool:
    needs = job.get("needs", [])
    if isinstance(needs, str):
        return needs == DEPLOYMENT_GATE
    return isinstance(needs, list) and DEPLOYMENT_GATE in needs


def _permission_violations(
    path: PurePosixPath,
    workflow: Mapping[str, Any],
    automatic: bool,
) -> list[str]:
    violations: list[str] = []
    top_permissions = workflow.get("permissions")
    if automatic and top_permissions != {"contents": "read"}:
        violations.append(
            f"{path}: automatic workflows must use only top-level contents: read"
        )
    if isinstance(top_permissions, Mapping) and top_permissions.get("packages") == "write":
        violations.append(f"{path}: top-level packages: write is forbidden")

    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, Mapping):
        return violations
    for job_id, job in jobs.items():
        if not isinstance(job, Mapping) or "permissions" not in job:
            continue
        permissions = job.get("permissions")
        if automatic and permissions != {"contents": "read"}:
            violations.append(
                f"{path}:{job_id}: automatic job permissions exceed contents: read"
            )
        if isinstance(permissions, Mapping) and permissions.get("packages") == "write":
            violations.append(f"{path}:{job_id}: packages: write is forbidden")
    return violations


_RUN_RISKS = (
    ("registry login", re.compile(r"\bdocker\s+login\b", re.IGNORECASE)),
    ("registry publication", re.compile(r"\bdocker\s+(?:image\s+)?push\b", re.IGNORECASE)),
    (
        "registry publication",
        re.compile(r"\bdocker\s+buildx\s+build\b[^\n]*\s--push\b", re.IGNORECASE),
    ),
    ("SSH connection", re.compile(r"(?m)^\s*(?:sudo\s+)?(?:ssh|scp)\b")),
    (
        "compose deployment command",
        re.compile(
            r"\bdocker\s+compose\b[^\n]*\b(?:up|restart|pull)\b|"
            r"\bdocker\s+compose\b[^\n]*\brun\b[^\n]*\bmigrate\b",
            re.IGNORECASE,
        ),
    ),
    (
        "service mutation",
        re.compile(
            r"\b(?:systemctl\s+(?:reload|restart|start)|service\s+\S+\s+restart|"
            r"kubectl\s+(?:apply|rollout|set\s+image)|helm\s+upgrade|terraform\s+apply)\b",
            re.IGNORECASE,
        ),
    ),
)

_AUTOMATIC_ONLY_RUN_RISKS = (
    ("migration command", re.compile(r"\balembic\s+upgrade\b", re.IGNORECASE)),
    ("migration command", re.compile(r"\bmanage\.py\s+migrate\b", re.IGNORECASE)),
)


def _step_risks(step: Mapping[str, Any], automatic: bool) -> list[str]:
    risks: list[str] = []
    uses = str(step.get("uses", "")).lower()
    if "login-action@" in uses:
        risks.append("registry login action")
    if "ssh-action@" in uses or "scp-action@" in uses:
        risks.append("SSH action")
    if "docker/build-push-action@" in uses:
        options = step.get("with", {})
        push = options.get("push") if isinstance(options, Mapping) else None
        if not _is_false(push):
            risks.append("docker/build-push-action must set literal push: false")

    run = str(step.get("run", ""))
    patterns = _RUN_RISKS + (_AUTOMATIC_ONLY_RUN_RISKS if automatic else ())
    for label, pattern in patterns:
        if pattern.search(run):
            risks.append(label)
    return risks


def _job_risks(job: Mapping[str, Any], automatic: bool) -> list[str]:
    risks: list[str] = []
    if "secrets" in job or any(
        _SECRET_REF.search(value) for value in _walk_scalars(job)
    ):
        risks.append("secret reference")
    if automatic and "environment" in job:
        risks.append("deployment environment access")
    steps = job.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, Mapping):
                risks.extend(_step_risks(step, automatic))
    return sorted(set(risks))


def _validate_automatic_workflow(
    path: PurePosixPath, workflow: Mapping[str, Any]
) -> list[str]:
    violations: list[str] = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, Mapping):
        return [f"{path}: jobs must be a mapping"]

    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            violations.append(f"{path}:{job_id}: job must be a mapping")
            continue
        name = str(job.get("name", job_id))
        if "deploy" in str(job_id).lower() or "deploy" in name.lower():
            violations.append(
                f"{path}:{job_id}: deploy-named jobs are forbidden in automatic workflows"
            )
        for risk in _job_risks(job, automatic=True):
            violations.append(f"{path}:{job_id}: {risk} is forbidden in automatic CI")
    return violations


def _gate_violations(
    path: PurePosixPath,
    workflow: Mapping[str, Any],
    risky_jobs: Mapping[str, list[str]],
) -> list[str]:
    violations: list[str] = []
    events = _event_names(workflow)
    if events != {"workflow_dispatch"}:
        violations.append(
            f"{path}: deployment-capable workflows must be workflow_dispatch only"
        )

    trigger_config = workflow.get("on", {})
    dispatch = (
        trigger_config.get("workflow_dispatch", {})
        if isinstance(trigger_config, Mapping)
        else {}
    )
    inputs = dispatch.get("inputs", {}) if isinstance(dispatch, Mapping) else {}
    confirmation = inputs.get("confirmation", {}) if isinstance(inputs, Mapping) else {}
    if (
        not isinstance(confirmation, Mapping)
        or confirmation.get("required") is not True
        or confirmation.get("type") != "string"
        or "default" in confirmation
    ):
        violations.append(f"{path}: deployment confirmation input must be required")

    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, Mapping):
        return violations
    gate = jobs.get(DEPLOYMENT_GATE)
    if not isinstance(gate, Mapping):
        violations.append(f"{path}: missing {DEPLOYMENT_GATE} job")
        return violations
    if _job_risks(gate, automatic=False):
        violations.append(f"{path}:{DEPLOYMENT_GATE}: gate must not use secrets or deploy")

    gate_text = "\n".join(_walk_scalars(gate))
    required_gate_fragments = (
        "vars.DEPLOYMENTS_ENABLED",
        "inputs.confirmation",
        '"$DEPLOYMENTS_ENABLED" != "true"',
        f'"$CONFIRMATION" != "{CONFIRMATION}"',
        "maintenance-only mode",
    )
    for fragment in required_gate_fragments:
        if fragment not in gate_text:
            violations.append(
                f"{path}:{DEPLOYMENT_GATE}: missing fail-closed check {fragment!r}"
            )

    for job_id in risky_jobs:
        job = jobs.get(job_id)
        if not isinstance(job, Mapping):
            continue
        if not _needs_gate(job):
            violations.append(f"{path}:{job_id}: deployment job must need {DEPLOYMENT_GATE}")
        condition = " ".join(str(job.get("if", "")).split())
        expected = (
            "${{ vars.DEPLOYMENTS_ENABLED == 'true' && "
            f"inputs.confirmation == '{CONFIRMATION}' "
            "}}"
        )
        if condition != expected:
            violations.append(
                f"{path}:{job_id}: deployment condition must exactly require both opt-ins"
            )
    return violations


def validate_workflows(
    workflows: Mapping[PurePosixPath, Mapping[str, Any]],
) -> list[str]:
    """Return deterministic maintenance-boundary violations."""
    violations: list[str] = []
    for path in sorted(workflows, key=str):
        workflow = workflows[path]
        events = _event_names(workflow)
        automatic = bool(events & {"push", "pull_request"})
        top_env = workflow.get("env", {})
        if any(_SECRET_REF.search(value) for value in _walk_scalars(top_env)):
            violations.append(f"{path}: top-level secret references are forbidden")
        violations.extend(_permission_violations(path, workflow, automatic))
        if automatic:
            violations.extend(_validate_automatic_workflow(path, workflow))

        jobs = workflow.get("jobs", {})
        risky_jobs: dict[str, list[str]] = {}
        if isinstance(jobs, Mapping):
            for job_id, job in jobs.items():
                if not isinstance(job, Mapping) or job_id == DEPLOYMENT_GATE:
                    continue
                risks = _job_risks(job, automatic=False)
                if risks:
                    risky_jobs[str(job_id)] = risks
        if risky_jobs:
            violations.extend(_gate_violations(path, workflow, risky_jobs))
    return sorted(set(violations))


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _tracked_workflows(root: Path) -> dict[PurePosixPath, dict[str, Any]]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", str(WORKFLOW_DIR)],
        cwd=root,
        check=True,
        capture_output=True,
    )
    workflows: dict[PurePosixPath, dict[str, Any]] = {}
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = PurePosixPath(raw_path.decode())
        if relative.suffix not in {".yml", ".yaml"}:
            continue
        path = root / relative
        workflows[relative] = load_workflow_text(path.read_text(), str(relative))
    return workflows


def main() -> int:
    root = _repo_root()
    workflows = _tracked_workflows(root)
    violations = validate_workflows(workflows)
    if violations:
        print("Maintenance-mode workflow guardrail failed:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(workflows)} tracked workflows preserve the maintenance-only boundary."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
