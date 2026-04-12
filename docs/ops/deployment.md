# Deployment

## Overview

Production runs on a Hetzner VM using Docker Compose. Cloudflare fronts inbound traffic to the VM. Deployments are orchestrated through GitHub Actions, which build and publish container images and then update services on the server.

---

## Server Setup (One-Time)

Before the first deployment, prepare the Hetzner server:

```bash
# SSH into the server
ssh root@<your-server-ip>

# Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Create project directory
mkdir -p /opt/sports-data-api
cd /opt/sports-data-api

# Clone the repository
git clone https://github.com/dock108/sports-data-admin-util.git .

# Create the production .env file (from .env.example)
nano infra/.env

# Login to GitHub Container Registry
echo $GHCR_TOKEN | docker login ghcr.io -u dock108 --password-stdin

# Pull initial images
cd infra
docker compose --profile prod pull

# Run initial migrations
docker compose --profile prod run --rm migrate

# Start all services
docker compose --profile prod up -d
```

### Prerequisites

- A Hetzner VM reachable over SSH
- Docker installed
- A DNS record pointing at the VM (Cloudflare recommended)
- `infra/.env` created on the server (from `infra/.env.example`)

### Edge Routing (Caddy)

The canonical sports-data-admin site block lives at `infra/Caddyfile`.

When `infra/Caddyfile` changes in a deploy commit, the deploy workflow automatically updates the active Caddy config on the server via `infra/scripts/update_caddy_site_block.py`, validates it, and reloads Caddy. No manual intervention is needed for route changes committed to the repo.

All FastAPI route prefixes (`/api/*`, `/auth/*`, `/v1/*`, `/healthz`, `/docs`, `/openapi.json`) must be routed to `localhost:8000`. Everything else goes to the Next.js admin UI on `localhost:3000`.

**Common pitfall:** Avoid `handle_path` which strips the matched prefix:
```caddy
# DON'T DO THIS - strips /api prefix
handle_path /api/* {
  reverse_proxy localhost:8000
}
```

With `handle_path`, a request to `/api/admin/sports/games` becomes `/admin/sports/games` upstream, causing FastAPI to return 404.

**Another pitfall:** Forgetting to route `/auth/*` to FastAPI. Without it, auth requests (login, signup, etc.) fall through to Next.js, which rejects them with its own Basic auth middleware — returning a misleading `401 Basic realm="Sports Admin"` that looks like a Caddy issue.

### Domain Cutover Checklist (`sda.dock108.dev`)

Use this checklist when replacing the production hostname.

1. Update DNS in Cloudflare so `sda.dock108.dev` resolves to the VM.
2. Set production URL env values in `infra/.env` on the server:
   - `FRONTEND_URL=https://sda.dock108.dev`
   - `ALLOWED_CORS_ORIGINS=https://sda.dock108.dev`
   - `ADMIN_ORIGINS=https://sda.dock108.dev` (if origin-based admin checks are used)
   - `NEXT_PUBLIC_SPORTS_API_URL=https://sda.dock108.dev`
3. Deploy using `backend-ci-cd.yml` so the Caddy site block sync logic runs.
4. Confirm `/etc/caddy/Caddyfile` only contains the new site block and remove any stale `sports-data-admin.dock108.ai` block from previous deploys.
5. Validate and reload Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

6. Run post-cutover checks:

```bash
curl -f https://sda.dock108.dev/healthz
curl -f https://sda.dock108.dev/api/health
```

Then verify login, admin proxy pages, realtime features, and password reset/magic-link flows from the browser.

---

## CI/CD Workflows

Two GitHub Actions workflows handle the build and deploy pipeline.

### `backend-ci-cd.yml` — Build & Deploy

**Triggers:**
- Push to `main` — runs tests, builds images, deploys to server
- Pull request to `main` — runs tests, builds images (no deploy)
- Manual `workflow_dispatch` with `full_deploy=true` — full pipeline including deploy

**Jobs (5, sequential):**

1. **test-scraper** — Installs scraper via `uv`, runs `pytest` with 80% coverage threshold
2. **test-api** — Installs API deps, runs `pytest` with 80% coverage threshold
3. **lint-web** — Installs pnpm deps, runs `tsc --noEmit` and `pnpm lint`
4. **compile** — After all tests pass: compiles Python (`compileall`) and Next.js (`pnpm build`)
5. **build** — Builds and pushes Docker images for all 3 services (api, web, scraper) to GHCR
6. **deploy** — SSHs to server, pulls images, runs migrations, restarts services (only on main push or manual full_deploy)

**Image tags:**
- Push to main: `ghcr.io/<repo>-<service>:<short-sha>` + `:latest`
- Pull request: `ghcr.io/<repo>-<service>:pr-<number>-<short-sha>` + `:latest`

**Deploy script behavior:**
1. Ensures server directory exists, fetches latest code, resets to branch
2. If `infra/Caddyfile` changed in the commit range: updates server Caddy config, validates, reloads
3. Logs into GHCR, pulls images
4. Runs migrations via the `migrate` service
5. Starts all services with `docker compose --profile prod up -d`
6. Prunes old images, prints service status

### `deploy-recent-image.yml` — Deploy Specific Tag

**Trigger:** Manual `workflow_dispatch` only, with optional `image_tag` input (defaults to `latest`).

Used for deploying a specific previously-built image without re-running the full CI pipeline. Useful for rollbacks or deploying a known-good image.

**Behavior:** Same as the deploy step above (fetch code, pull images, migrate, restart) but uses the specified `IMAGE_TAG` environment variable.

---

## GitHub Secrets

Configure these in Settings → Secrets and variables → Actions:

| Secret | Description |
|--------|-------------|
| `DEPLOY_HOST` | Server IP address |
| `DEPLOY_USER` | SSH user (typically `root`) |
| `DEPLOY_SSH_KEY` | Private SSH key for authentication |
| `DEPLOY_PATH` | Project path on server (`/opt/sports-data-api`) |
| `GHCR_TOKEN` | GitHub PAT with `write:packages` permission |

**Setting up GHCR_TOKEN:**
1. GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate token with `write:packages`, `read:packages` scopes
3. Add as repository secret `GHCR_TOKEN`

**Setting up SSH key:**
1. Generate: `ssh-keygen -t ed25519 -C "github-actions-deploy"`
2. Add public key to server's `~/.ssh/authorized_keys`
3. Add private key as `DEPLOY_SSH_KEY` secret

---

## Environment Variables

Production secrets live only on the server in `infra/.env` (never committed). Use `infra/.env.example` as template.

**Required categories:**
- **Database/Redis**: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`, `REDIS_PASSWORD`
- **Runtime**: `ENVIRONMENT=production`, `ALLOWED_CORS_ORIGINS`
- **Authentication**: `API_KEY` (min 32 chars, generate with `openssl rand -hex 32`), `JWT_SECRET` (generate with `openssl rand -hex 32`)
- **Auth Settings** (optional): `AUTH_ENABLED` (default `true`; set `false` to bypass role checks), `JWT_EXPIRE_MINUTES` (default `1440` = 24h)
- **External APIs**: `ODDS_API_KEY`, `X_AUTH_TOKEN`, `X_CT0`
- **Frontend**: `NEXT_PUBLIC_SPORTS_API_URL`, `FRONTEND_URL`

---

## Rollback Strategy

Two approaches:

**Option 1: Deploy a previous image tag** (preferred)

Use the `deploy-recent-image` workflow with the commit SHA of the known-good build:
1. Go to Actions → Deploy Recent Image → Run workflow
2. Enter the image tag (e.g., `a1b2c3d`)

**Option 2: Manual rollback on server**

```bash
ssh root@<server-ip>
cd /opt/sports-data-api/infra

# Pull a specific image tag
docker compose --profile prod pull
docker compose --profile prod up -d
```

**Note:** Database migrations are not auto-rolled back. Revert migrations manually before running older images if the deploy included schema changes.

---

## Troubleshooting

### Deployment fails with "permission denied" on SSH
- Verify `DEPLOY_SSH_KEY` contains the complete private key
- Ensure public key is in server's `~/.ssh/authorized_keys`
- Check permissions: `chmod 600 ~/.ssh/authorized_keys`

### Images fail to pull from GHCR
- Verify `GHCR_TOKEN` has correct permissions
- Check if token has expired
- Test manually: `echo $GHCR_TOKEN | docker login ghcr.io -u dock108 --password-stdin`

### Service health checks fail
- Check logs: `docker compose --profile prod logs <service>`
- Verify `infra/.env` variables
- Check migration logs: `docker compose --profile prod logs migrate`

### Manual deployment
```bash
ssh root@<server-ip>
cd /opt/sports-data-api/infra

echo $GHCR_TOKEN | docker login ghcr.io -u dock108 --password-stdin
docker compose --profile prod pull
docker compose --profile prod run --rm migrate
docker compose --profile prod up -d
docker compose --profile prod ps
```

---

## Guardrails

- **Do not** edit production files on VM without committing to repo (except `.env`)
- **Migrations**: Run explicitly via `migrate` service, not at startup
- **Debug failures**: Start with GitHub Actions logs, then check container logs
