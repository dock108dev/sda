# Sports Data Admin

**Status: Maintenance only. This repository is retained for dependency,
security, and build maintenance. It is not currently deployable, and GitHub
Actions do not publish images or deploy from main.**

Sports Data Admin is the backend service for Scroll Down Sports catch-up data. It serves compact game lists and normalized game detail feeds built from play-by-play, player stats, team stats, and box scores.

The current runtime is intentionally small:

- FastAPI API at `api/`
- Celery scraper worker and beat scheduler at `scraper/`
- Docker/runtime assets at `infra/`
- Optional local admin web app at `web/`

## Run Locally

```bash
cd infra
cp .env.example .env
docker compose --profile dev up -d --build
```

Local endpoints:

- Admin UI: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/healthz`

## Maintenance Contract

Pull requests, pushes to `main`, and Dependabot changes continue to run tests,
linting, dependency and security audits, secret scanning, application builds,
and container builds. Container builds remain inside the GitHub Actions runner
with `push: false`; CI has read-only repository permissions and does not log in
to a registry.

Deployment documentation and assets are retained as inactive history. Do not
provision deployment secrets or use the historical production procedure. See
[`docs/ops/deployment.md`](docs/ops/deployment.md) for the fail-closed gate and
the separate contract for reconsidering deployment.

## Documentation

Start with [`docs/index.md`](docs/index.md).

Useful references:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/api.md`](docs/api.md)
- [`docs/env-and-config.md`](docs/env-and-config.md)
- [`docs/scheduler-and-jobs.md`](docs/scheduler-and-jobs.md)
- [`docs/ops/infra.md`](docs/ops/infra.md)
- [`docs/ops/security.md`](docs/ops/security.md)
- [`docs/maintenance/oversized-files.md`](docs/maintenance/oversized-files.md)
