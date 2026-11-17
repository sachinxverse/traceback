#!/usr/bin/env bash
# Restore a pg_dump custom-format file into a fresh database (Issue 4).
# Usage: ./scripts/restore_db.sh backup.dump postgresql://user:pass@host/db
# Verify: the script prints row counts per key table before and after.
set -euo pipefail
DUMP="${1:?usage: restore_db.sh backup.dump TARGET_DATABASE_URL}"
: "${2:?usage: restore_db.sh backup.dump TARGET_DATABASE_URL}"
TARGET="$2"

psql "$TARGET" -c "select 'rows before restore:' as phase;"
for t in users institutions reports report_images matches claims messages otp_challenges audit_log; do
  n=$(psql -t -A "$TARGET" -c "select count(*) from information_schema.tables where table_name='$t';")
  if [ "$n" != "0" ]; then
    echo "$t: $(psql -t -A "$TARGET" -c "select count(*) from $t;") rows (pre-existing!)"
  fi
done

pg_restore --clean --if-exists --no-owner --no-privileges -d "$TARGET" "$DUMP"

psql "$TARGET" -c "select 'rows after restore:' as phase;"
for t in users institutions reports report_images matches claims messages otp_challenges audit_log; do
  n=$(psql -t -A "$TARGET" -c "select count(*) from information_schema.tables where table_name='$t';")
  if [ "$n" != "0" ]; then
    echo "$t: $(psql -t -A "$TARGET" -c "select count(*) from $t;") rows"
  fi
done
echo "restore complete: $DUMP -> $TARGET"
