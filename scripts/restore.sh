#!/usr/bin/env bash
# Restore only after the operator has reviewed and confirmed the target deployment.
set -euo pipefail
umask 077

if [[ $# -ne 2 || "$2" != "--confirm" || ! -f "$1" || ! -s "$1" ]]; then
  printf 'Usage: %s <archive.dump> --confirm\nStop the API and verify the target configuration first.\n' "$0" >&2
  exit 2
fi
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${COMPOSE_ENV_FILE:-"$ROOT/docker/.env"}

docker compose --env-file "$ENV_FILE" -f "$ROOT/docker/compose.yml" exec -T postgres \
  sh -c 'exec pg_restore --exit-on-error --single-transaction --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$1"
printf 'Database restore completed. Verify migrations and readiness before restarting the API.\n'
