#!/bin/sh
# Pack everything ColdOps needs into /tmp/coldops-move, on the OLD server.
# Read-only: it copies, it never stops anything.
#
# For the real move the operator stops the old server's work first (see
# README.md), so the copy is final and nothing is sent, read or warmed twice.
#
# The databases are dumped, not copied as volume files: a dump restores on any
# CPU (the new server is ARM, this one is x86). Temporal's two databases go
# too, because they hold the schedules, their paused state and every campaign
# loop -- recreating them from the CLI would lose all three.
set -eu
OUT=/tmp/coldops-move
cd /opt/coldops
rm -rf "$OUT" && mkdir -p "$OUT"

docker exec deploy-postgres-1 pg_dump -U titan -d titan -Fc > "$OUT/titan.dump"
for db in temporal temporal_visibility; do
    docker exec deploy-temporal-postgres-1 pg_dump -U temporal -d "$db" -Fc > "$OUT/$db.dump"
done
# The working tree with .env, secrets/, the TLS server blocks and logs/; the
# old daily dumps stay behind (the fresh one above supersedes them).
tar czf "$OUT/tree.tgz" --exclude=./backups -C /opt/coldops .
tar czf "$OUT/letsencrypt.tgz" -C /etc letsencrypt
tar czf "$OUT/volumes.tgz" -C /var/lib/docker/volumes \
    deploy_artifacts/_data deploy_oauth_tokens/_data
docker exec -i deploy-postgres-1 psql -U titan -d titan -At -f - > "$OUT/COUNTS" <<'SQL'
SELECT (SELECT count(*) FROM leads) || ' leads, '
    || (SELECT count(*) FROM messages) || ' messages, '
    || (SELECT count(*) FROM message_drafts) || ' drafts';
SQL
(cd "$OUT" && sha256sum ./*.dump ./*.tgz COUNTS > SHA256SUMS)
du -sh "$OUT"
cat "$OUT/COUNTS"
