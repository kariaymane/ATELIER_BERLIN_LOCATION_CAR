#!/usr/bin/env bash
# Back up the configured Compose database without putting exports in source control.
set -euo pipefail
umask 077

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${COMPOSE_ENV_FILE:-"$ROOT/docker/.env"}
BACKUP_DIR=${BACKUP_DIR:-"${XDG_DATA_HOME:-$HOME/.local/share}/atelier-berlin/backups"}
mkdir -p -- "$BACKUP_DIR"
BACKUP_FILE=$(mktemp "$BACKUP_DIR/database-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.dump")
trap 'rm -f -- "$BACKUP_FILE"' EXIT

docker compose --env-file "$ENV_FILE" -f "$ROOT/docker/compose.yml" exec -T postgres \
  sh -c 'exec pg_dump --format=custom --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  > "$BACKUP_FILE"

test -s "$BACKUP_FILE"
trap - EXIT
printf 'Database backup saved to %s\n' "$BACKUP_FILE"
