#!/bin/bash
set -e
BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sql"
echo "Starting PostgreSQL backup to $BACKUP_FILE"
docker exec car_rental_db_prod pg_dump -U ${POSTGRES_USER:-rental_app} ${POSTGRES_DB:-car_rental} > $BACKUP_FILE
echo "Backup complete: $BACKUP_FILE"
