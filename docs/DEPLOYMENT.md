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

If you use Caddy at the edge, ensure `/api/*` routes to the FastAPI container without stripping the prefix.

**Caddyfile example:**
```caddy
sports-data-admin.dock108.ai {
  encode gzip

  # API routes (preserve /api prefix)
  handle /api/* {
    reverse_proxy localhost:8000
  }

  # Web app
  handle {
    reverse_proxy localhost:3000
  }
}
```

**Common pitfall:** Avoid `handle_path` which strips the matched prefix:
```caddy
# DON'T DO THIS - strips /api prefix
handle_path /api/* {
  reverse_proxy localhost:8000
}
```

With `handle_path`, a request to `/api/admin/sports/games` becomes `/admin/sports/games` upstream, causing FastAPI to return 404.

---

## Deploy Flow

1. **Trigger**: Deploy runs on merge to `main` or manual workflow dispatch
2. **Change detection**: GitHub Actions detects which services changed
3. **Tests**: Unit tests run for API and scraper changes
4. **Build**: Images are built and pushed to GHCR with `latest` and commit-sha tags
5. **Server update**: SSH to server, pull images, run migrations, restart changed services
6. **Health checks**: Each service is verified healthy before proceeding

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
- **Database/Redis**: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`
- **Runtime**: `ENVIRONMENT=production`, `ALLOWED_CORS_ORIGINS`
- **Authentication**: `API_KEY` (min 32 chars, generate with `openssl rand -hex 32`), `JWT_SECRET` (generate with `openssl rand -hex 32`)
- **Auth Settings** (optional): `AUTH_ENABLED` (default `true`; set `false` to bypass role checks), `JWT_EXPIRE_MINUTES` (default `1440` = 24h)
- **External APIs**: `ODDS_API_KEY`, `X_AUTH_TOKEN`, `X_CT0`
- **Frontend**: `NEXT_PUBLIC_SPORTS_API_URL`

---

## Rollback Strategy

Rollbacks use previous GHCR image tags (commit-sha):

```bash
# On server, update image tag to previous SHA
# Then:
docker compose --profile prod pull <service>
docker compose --profile prod up -d <service>
```

**Note:** Database migrations are not auto-rolled back. Revert migrations manually before running older images.

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
