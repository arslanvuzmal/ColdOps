#!/bin/sh
# Build ColdOps on the NEW server (Oracle, Ubuntu 24.04, ARM) from the kit in
# /tmp/coldops-move. Run as root: sudo sh setup.sh [--final]
#
#   without --final   rehearsal: restores and checks, then stops everything,
#                     so the old server stays the only one doing work.
#   --final           restores the cutover copy and starts the whole stack.
#
# Safe to run again: each run starts from a clean restore.
set -eu
K=/tmp/coldops-move
MODE=${1:-}
cd "$K" && sha256sum -c --quiet SHA256SUMS && echo "kit: checksums OK"

# --- the machine --------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    apt-get update -q
    apt-get install -yq docker.io docker-compose-v2 certbot
fi
systemctl enable --now docker >/dev/null

# Oracle's Ubuntu image has its own iptables rules that refuse everything but
# SSH, on top of the cloud firewall (the security list, opened in the console).
for port in 80 443; do
    if ! iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
        at=$(iptables -L INPUT --line-numbers -n | awk '/REJECT/ {print $1; exit}')
        if [ -n "$at" ]; then
            iptables -I INPUT "$at" -p tcp --dport "$port" -j ACCEPT
        else
            iptables -A INPUT -p tcp --dport "$port" -j ACCEPT
        fi
    fi
done
if command -v netfilter-persistent >/dev/null; then
    netfilter-persistent save >/dev/null 2>&1 || true
fi

# --- the files ----------------------------------------------------------
if [ -x /opt/coldops/deploy/compose.sh ]; then
    /opt/coldops/deploy/compose.sh down >/dev/null 2>&1 || true
fi
mkdir -p /opt/coldops
tar xzf "$K/tree.tgz" -C /opt/coldops
tar xzf "$K/letsencrypt.tgz" -C /etc
cd /opt/coldops
git remote set-url origin https://github.com/arslanvuzmal/ColdOps.git 2>/dev/null || true

# --- images, built here so they are ARM ---------------------------------
docker build -q -f apps/api/Dockerfile -t coldops-api:local . >/dev/null
docker build -q -f apps/web/Dockerfile \
    --build-arg NEXT_PUBLIC_API_URL=https://coldops.arslanvuzmallone.com \
    -t coldops-web:local . >/dev/null
docker build -q -t coldops-browser-worker:local apps/browser-worker >/dev/null
echo "images: built for $(uname -m)"

# --- the data -----------------------------------------------------------
# Fresh volumes every run, so a rerun restores into empty databases.
for v in deploy_postgres_data deploy_temporal_postgres_data deploy_artifacts \
         deploy_oauth_tokens deploy_redis_data; do
    docker volume rm "$v" >/dev/null 2>&1 || true
done
deploy/compose.sh create >/dev/null 2>&1
tar xzf "$K/volumes.tgz" -C /var/lib/docker/volumes
deploy/compose.sh up -d postgres temporal-postgres >/dev/null 2>&1
for c in deploy-postgres-1 deploy-temporal-postgres-1; do
    i=0
    until [ "$(docker inspect -f '{{.State.Health.Status}}' "$c")" = healthy ]; do
        i=$((i + 1))
        if [ "$i" -gt 60 ]; then echo "$c never became healthy"; exit 1; fi
        sleep 2
    done
done
docker cp "$K/titan.dump" deploy-postgres-1:/tmp/titan.dump
docker exec deploy-postgres-1 pg_restore -U titan -d titan --no-owner -j 4 /tmp/titan.dump
for db in temporal temporal_visibility; do
    docker cp "$K/$db.dump" "deploy-temporal-postgres-1:/tmp/$db.dump"
    docker exec deploy-temporal-postgres-1 psql -U temporal -d postgres -qc "CREATE DATABASE $db" 2>/dev/null || true
    docker exec deploy-temporal-postgres-1 pg_restore -U temporal -d "$db" --no-owner "/tmp/$db.dump"
done
got=$(docker exec -i deploy-postgres-1 psql -U titan -d titan -At -f - <<'SQL'
SELECT (SELECT count(*) FROM leads) || ' leads, '
    || (SELECT count(*) FROM messages) || ' messages, '
    || (SELECT count(*) FROM message_drafts) || ' drafts';
SQL
)
want=$(cat "$K/COUNTS")
if [ "$got" != "$want" ]; then
    echo "RESTORE MISMATCH: got '$got', want '$want'"
    exit 1
fi
echo "database: restored and matches the old server ($got)"

# --- the timers ---------------------------------------------------------
cp deploy/systemd/coldops-*.service deploy/systemd/coldops-*.timer /etc/systemd/system/
systemctl daemon-reload

if [ "$MODE" != "--final" ]; then
    # Rehearsal ends here: a second live stack would send, read and warm up
    # alongside the old one.
    deploy/compose.sh down >/dev/null 2>&1
    echo "REHEARSAL OK: everything restores. Nothing left running."
    exit 0
fi

deploy/compose.sh up -d 2>&1 | tail -3
systemctl enable --now coldops-heal.timer coldops-backup.timer >/dev/null 2>&1 || true
systemctl enable --now certbot.timer >/dev/null 2>&1 || true
i=0
until [ "$(docker ps --filter health=healthy -q | wc -l)" -ge 10 ]; do
    i=$((i + 1))
    if [ "$i" -gt 90 ]; then break; fi
    sleep 5
done
docker ps --format '{{.Names}} {{.Status}}' | sort
echo "LIVE. Point the DNS A record of coldops.arslanvuzmallone.com at this server."
