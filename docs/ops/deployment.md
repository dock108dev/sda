# Deployment (Inactive)

**Status: maintenance only. Sports Data Admin is not currently deployable.**
GitHub Actions do not publish images or deploy from `main`, pull requests, or
Dependabot merges. This page retains operational history without authorizing or
instructing a production deployment.

## Current Maintenance Contract

`.github/workflows/backend-ci-cd.yml` is CI only. It runs tests, coverage,
linting, type and schema checks, dependency/security audits, secret scanning,
application compilation, and container builds with `push: false`. It has only
`contents: read` permission, does not authenticate to GHCR, and has no SSH,
migration, restart, or deployment job.

`.github/workflows/deploy-recent-image.yml` retains the historical procedure in
a separate manual-only workflow. Its first job is a credential-free maintenance
gate. The deployment job cannot be scheduled unless both conditions are true:

- repository variable `DEPLOYMENTS_ENABLED` is exactly `true`;
- the dispatcher types `DEPLOY SPORTS DATA ADMIN` exactly.

`DEPLOYMENTS_ENABLED` is intentionally absent or false in maintenance mode. A
normal dispatch therefore exits at the gate with a maintenance-only message,
before any deployment secret, registry login, SSH action, migration, or service
restart is reached. Do not set the variable or provision deployment credentials
under the current repository contract.

The manual realtime load-test workflow is unrelated to deployment. Its Alembic
migration targets an ephemeral PostgreSQL service created inside the GitHub
Actions runner.

## Historical Production Shape

Before maintenance-only mode, the repository had two deployment paths:

- pushes to `main` built API, web, and scraper images, published commit and
  `latest` tags to GHCR, then opened an SSH session to the deployment target;
- a manual recent-image workflow selected an existing tag and opened the same
  SSH deployment path.

The server-side procedure historically synchronized the checkout, updated the
Caddy site block, authenticated to GHCR, pulled images, ran Alembic through the
`migrate` Compose service, recreated application services, checked API health,
refreshed materialized card feeds, verified the normalized feed contract, and
pruned superseded Docker artifacts. Rollback historically selected an earlier
image tag and restarted the application services, with schema compatibility
considered separately.

Those details are preserved for context only. They do not describe an active,
supported, or validated deployment target, and they must not be used as a
runbook while the repository is in maintenance-only mode.

## CI Workflows

- `backend-ci-cd.yml`: CI-only validation for pull requests, `main`, and manual
  CI runs; image builds remain local to the runner.
- `deploy-recent-image.yml`: historical manual deployment procedure protected
  by the fail-closed maintenance gate.
- `realtime-load-test.yml`: manual, runner-local load harness for the
  non-production realtime test endpoint and Redis Streams path.

The deterministic `scripts/check_maintenance_mode.py` guardrail scans every
tracked workflow. CI fails if an automatic workflow gains deployment behavior,
registry authentication, image publication, deployment credentials, production
migrations, or service mutation, or if a manual deployment bypasses the gate.

## Reopening Deployment

Deployment may be reconsidered only through a separate owner-authorized task.
That task must provide and validate all of the following before enabling the
repository variable or exercising deployment code:

- explicit owner authorization;
- a defined, current deployment target;
- a current secret and access review;
- a current image-registry decision;
- a server checkout and migration strategy;
- verified backup and rollback procedures;
- proof on staging or a disposable target;
- a deliberate choice between manual and automatic deployment.

The maintenance-only conversion does not satisfy or begin any of those steps.
