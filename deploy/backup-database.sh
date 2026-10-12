#!/bin/sh
# Daily database backup, kept for a week.
#
# Found in the 11 Oct 2026 review: the only backups were two taken by hand on
# 9 Oct. A lost disk would have lost every lead, every reply and -- the one
# that matters most -- the suppression list, the record of who asked never to
# be written to again.
#
# pg_dump in custom format (restorable table by table with pg_restore),
# written to a temporary name and renamed only once complete, so a dump cut
# short is never mistaken for a good one. Keeps the newest $KEEP daily dumps.
# Run once a day by coldops-backup.timer (deploy/systemd/).
#
# This is a copy on the same server: it protects against a bad migration or a
# deleted table, not against losing the server. Copy the newest dump off the
# machine for that (see install-backups.sh).

set -eu

DIR=${COLDOPS_BACKUP_DIR:-/opt/coldops/backups}
KEEP=${COLDOPS_BACKUP_KEEP:-7}
CONTAINER=${COLDOPS_BACKUP_CONTAINER:-deploy-postgres-1}
LOG=${COLDOPS_HEAL_LOG:-/opt/coldops/logs/heal.log}

mkdir -p "$DIR" "$(dirname "$LOG")"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$DIR/daily-$stamp.dump"

if docker exec "$CONTAINER" pg_dump -U titan -d titan -Fc > "$target.partial" &&
   [ -s "$target.partial" ]; then
    mv "$target.partial" "$target"
    size=$(du -h "$target" | cut -f1)
    printf '{"at":"%s","container":"database","action":"backed_up","reason":"daily dump %s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$size" >> "$LOG"
else
    rm -f "$target.partial"
    printf '{"at":"%s","container":"database","action":"backup_failed","reason":"pg_dump failed; previous dumps kept"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
    exit 1
fi

# Rotate: newest $KEEP daily dumps stay; the hand-made ones are never touched.
ls -1t "$DIR"/daily-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old"
done
