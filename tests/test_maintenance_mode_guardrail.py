"""Focused regression tests for the maintenance-only workflow guardrail."""

from __future__ import annotations

import unittest
from pathlib import PurePosixPath

from scripts.check_maintenance_mode import load_workflow_text, validate_workflows

CI_PATH = PurePosixPath(".github/workflows/ci.yml")
DEPLOY_PATH = PurePosixPath(".github/workflows/deploy.yml")


def violations_for(text: str, path: PurePosixPath = CI_PATH) -> list[str]:
    workflow = load_workflow_text(text, str(path))
    return validate_workflows({path: workflow})


SAFE_CI = """
name: Backend CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v7
        with:
          push: false
"""

SAFE_GATED_DEPLOYMENT = """
name: Deployment (Maintenance-Gated)
on:
  workflow_dispatch:
    inputs:
      confirmation:
        required: true
        type: string
permissions:
  contents: read
jobs:
  maintenance-gate:
    runs-on: ubuntu-latest
    steps:
      - env:
          DEPLOYMENTS_ENABLED: ${{ vars.DEPLOYMENTS_ENABLED }}
          CONFIRMATION: ${{ inputs.confirmation }}
        run: |
          if [[ "$DEPLOYMENTS_ENABLED" != "true" ]]; then
            echo "maintenance-only mode"
            exit 1
          fi
          if [[ "$CONFIRMATION" != "DEPLOY SPORTS DATA ADMIN" ]]; then
            exit 1
          fi
  deploy:
    runs-on: ubuntu-latest
    needs: maintenance-gate
    if: ${{ vars.DEPLOYMENTS_ENABLED == 'true' && inputs.confirmation == 'DEPLOY SPORTS DATA ADMIN' }}
    steps:
      - uses: appleboy/ssh-action@v1.2.5
        with:
          host: ${{ secrets.DEPLOY_HOST }}
"""


class MaintenanceModeGuardrailTests(unittest.TestCase):
    def test_safe_ci_build_without_push_passes(self) -> None:
        self.assertEqual(violations_for(SAFE_CI), [])

    def test_automatic_image_push_is_rejected(self) -> None:
        unsafe = SAFE_CI.replace("push: false", "push: true")
        self.assertTrue(
            any("literal push: false" in violation for violation in violations_for(unsafe))
        )

    def test_registry_login_in_automatic_ci_is_rejected(self) -> None:
        unsafe = SAFE_CI.replace(
            "steps:", "steps:\n      - uses: docker/login-action@v4"
        )
        self.assertTrue(
            any("registry login" in violation for violation in violations_for(unsafe))
        )

    def test_package_write_permission_in_automatic_ci_is_rejected(self) -> None:
        unsafe = SAFE_CI.replace(
            "contents: read", "contents: read\n  packages: write"
        )
        self.assertTrue(
            any("packages: write" in violation for violation in violations_for(unsafe))
        )

    def test_deploy_named_job_in_automatic_ci_is_rejected(self) -> None:
        unsafe = SAFE_CI.replace("  build:", "  deploy:")
        self.assertTrue(
            any("deploy-named" in violation for violation in violations_for(unsafe))
        )

    def test_automatic_ssh_deploy_is_rejected(self) -> None:
        unsafe = SAFE_CI.replace(
            "steps:",
            "steps:\n      - uses: appleboy/ssh-action@v1.2.5\n"
            "        with:\n          host: ${{ secrets.DEPLOY_HOST }}",
        )
        found = violations_for(unsafe)
        self.assertTrue(any("SSH action" in violation for violation in found))
        self.assertTrue(any("secret reference" in violation for violation in found))

    def test_automatic_production_mutation_is_rejected(self) -> None:
        unsafe = SAFE_CI.replace(
            "steps:",
            "steps:\n      - run: docker compose --profile prod run --rm migrate",
        )
        self.assertTrue(
            any("compose deployment" in violation for violation in violations_for(unsafe))
        )

    def test_ungated_manual_deployment_is_rejected(self) -> None:
        unsafe = """
name: Manual deploy
on: workflow_dispatch
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1.2.5
        with:
          host: ${{ secrets.DEPLOY_HOST }}
"""
        found = violations_for(unsafe, DEPLOY_PATH)
        self.assertTrue(any("missing maintenance-gate" in item for item in found))

    def test_manual_deployment_requires_both_gate_checks(self) -> None:
        self.assertEqual(violations_for(SAFE_GATED_DEPLOYMENT, DEPLOY_PATH), [])
        unsafe = SAFE_GATED_DEPLOYMENT.replace(
            "vars.DEPLOYMENTS_ENABLED == 'true' && ", ""
        )
        self.assertTrue(
            any("exactly require both opt-ins" in item for item in violations_for(unsafe, DEPLOY_PATH))
        )


if __name__ == "__main__":
    unittest.main()
