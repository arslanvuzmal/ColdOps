#!/bin/sh
# The container doctor: restart a ColdOps container that is running but stuck.
#
# Docker's restart policy restarts a container that *exits*. It does nothing
# for one that is still running and failing its own health check -- a worker
# wedged on a dead database connection, an API that stopped answering -- and
# that is the failure nobody notices until a day of mail has not gone out.
#
# The known-safe tier of self-healing (programme item M), and nothing more:
#   * only containers of this stack (compose project "deploy"),
#   * only one Docker itself reports "unhealthy" (its own check failed several
#     times in a row, not once),
#   * at most MAX_PER_HOUR restarts per container; past that it stops trying,
#     writes "gave_up" and leaves it for a person -- a restart loop hides the
#     fault it is meant to fix.
# It never rolls back a deploy, edits configuration or touches data. Those
# stay human.
#
# Every action is one JSON line in $LOG, which the CRM's System page shows.
# Run every two minutes by coldops-heal.timer (deploy/systemd/).

set -eu

LOG=${COLDOPS_HEAL_LOG:-/opt/coldops/logs/heal.log}
STATE=${COLDOPS_HEAL_STATE:-/opt/coldops/logs/heal.state}
MAX_PER_HOUR=${COLDOPS_HEAL_MAX_PER_HOUR:-3}
PROJECT=${COLDOPS_HEAL_PROJECT:-deploy}

mkdir -p "$(dirname "$LOG")"
touch "$LOG" "$STATE"
now=$(date -u +%s)
stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

log() {  # container action reason
    printf '{"at":"%s","container":"%s","action":"%s","reason":"%s"}\n' \
        "$stamp" "$1" "$2" "$3" >> "$LOG"
}

# Keep only the last hour of restart times: lines "container epoch".
cutoff=$((now - 3600))
awk -v c="$cutoff" '$2 >= c' "$STATE" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"

docker ps --filter "label=com.docker.compose.project=$PROJECT" \
          --filter "health=unhealthy" --format '{{.Names}}' |
while read -r name; do
    [ -n "$name" ] || continue
    recent=$(awk -v n="$name" '$1 == n' "$STATE" | wc -l | tr -d ' ')
    if [ "$recent" -ge "$MAX_PER_HOUR" ]; then
        # Said once an hour, not every two minutes.
        said=$(awk -v n="$name-gaveup" '$1 == n' "$STATE" | wc -l | tr -d ' ')
        if [ "$said" -eq 0 ]; then
            log "$name" "gave_up" "unhealthy after $recent restarts in an hour; needs a person"
            echo "$name-gaveup $now" >> "$STATE"
        fi
        continue
    fi
    if docker restart "$name" >/dev/null 2>&1; then
        echo "$name $now" >> "$STATE"
        log "$name" "restarted" "health check failing"
    else
        log "$name" "restart_failed" "docker restart returned an error"
    fi
done
