#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE=${COMPOSE_FILE:-infra/docker-compose.yml}
COMPOSE_PROFILE=${COMPOSE_PROFILE:-prod}
API_BASE_URL=${API_BASE_URL:-http://localhost:8000}

required_services=(
  api
  postgres
  redis
  scraper
  web
)

log() {
  printf '%s\n' "$1"
}

fail() {
  log "ERROR: $1"
  exit 1
}

check_service_running() {
  local service="$1"
  local container_id
  container_id=$(docker compose -f "$COMPOSE_FILE" --profile "$COMPOSE_PROFILE" ps -q "$service")
  if [[ -z "$container_id" ]]; then
    fail "Service '$service' is not running (no container found)."
  fi

  local status
  status=$(docker inspect -f '{{.State.Status}}' "$container_id")
  if [[ "$status" != "running" ]]; then
    fail "Service '$service' is not running (status: $status)."
  fi

  local health
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")
  if [[ "$health" != "none" && "$health" != "healthy" ]]; then
    fail "Service '$service' is unhealthy (health: $health)."
  fi

  if [[ "$health" == "healthy" ]]; then
    log "OK: $service is running (health: healthy)"
  else
    log "OK: $service is running"
  fi
}

check_db_connectivity() {
  log "Checking database connectivity..."
  if ! docker compose -f "$COMPOSE_FILE" --profile "$COMPOSE_PROFILE" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null; then
    fail "Database connectivity check failed."
  fi
  log "OK: database is reachable"
}

check_endpoint() {
  local path="$1"
  local url="${API_BASE_URL}${path}"
  local status
  status=$(curl -sS -o /dev/null -w "%{http_code}" "$url")
  if [[ "$status" != "200" ]]; then
    fail "Endpoint check failed for $path (status: $status)."
  fi
  log "OK: $path returned 200"
}

log "Starting post-deploy verification..."
log "Using compose file: $COMPOSE_FILE"
log "Using compose profile: $COMPOSE_PROFILE"
log "Using API base URL: $API_BASE_URL"

log "Checking required services..."
for service in "${required_services[@]}"; do
  check_service_running "$service"
done

check_db_connectivity

log "Checking API endpoints..."
check_endpoint "/healthz"
check_endpoint "/api/admin/sports/games?limit=1"

log "Checking Scroll Down normalized card feed..."
python3 scripts/validate_scroll_down_feed.py \
  --base-url "$API_BASE_URL" \
  --env-file "${DEPLOY_ENV_FILE:-infra/.env}"

log "All checks passed."
