#!/usr/bin/env bash
# pg_dump of DATABASE_URL (Issue 4). Usage: DATABASE_URL=... ./scripts/backup_db.sh [outfile]
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL must be set}"
OUT="${1:-traceback_db_$(date +%Y%m%d_%H%M%S).dump}"
# Render internal URLs are plain postgres://; pg_dump understands them directly.
pg_dump --format=custom --no-owner --no-privileges -f "$OUT" "$DATABASE_URL"
echo "backup written: $OUT ($(du -h "$OUT" | cut -f1))"
