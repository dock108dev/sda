#!/bin/bash
set -euo pipefail

# Daily backup script - creates timestamped SQL dump
# Usage: /scripts/backup.sh
# Called automatically by backup container, or manually via:
#   docker exec sports-postgres /scripts/backup.sh

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/sports_${TIMESTAMP}.sql.gz"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

echo "Starting backup at $(date)..."
echo "Database: ${POSTGRES_DB:-sports}"
echo "Destination: $BACKUP_FILE"

# Create backup
pg_dump -U "${POSTGRES_USER:-sports}" -d "${POSTGRES_DB:-sports}" | gzip > "$BACKUP_FILE"

# Verify backup was created
if [ -f "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "Backup complete: $BACKUP_FILE ($SIZE)"
    
    # Create/update latest symlink.
    # Use a relative link so it works both inside the container (/backups/...)
    # and on the host filesystem (infra/backups/...).
    ln -sf "$(basename "$BACKUP_FILE")" "${BACKUP_DIR}/latest.sql.gz"
    
    # Keep only last 3 days of backups (~1.2GB each, ~3.6GB total)
    find "$BACKUP_DIR" -name "sports_*.sql.gz" -mtime +3 -delete
    echo "Cleaned up backups older than 3 days"
else
    echo "ERROR: Backup failed - file not created"
    exit 1
fi
