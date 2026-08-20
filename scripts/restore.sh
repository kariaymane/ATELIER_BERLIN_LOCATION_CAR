#!/bin/bash
set -e
if [ -z "$1" ]; then
  echo "Usage: $0 <backup_file.sql>"
  exit 1
fi
echo "Restoring from $1"
cat $1 | docker exec -i car_rental_db_prod psql -U ${POSTGRES_USER:-rental_app} ${POSTGRES_DB:-car_rental}
echo "Restore complete"
