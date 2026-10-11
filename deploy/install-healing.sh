#!/bin/sh
# Install the container doctor's timer on the host. Safe to re-run.
#
#   sh /opt/coldops/deploy/install-healing.sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p /opt/coldops/logs
install -m 0644 "$HERE/systemd/coldops-heal.service" /etc/systemd/system/coldops-heal.service
install -m 0644 "$HERE/systemd/coldops-heal.timer" /etc/systemd/system/coldops-heal.timer
systemctl daemon-reload
systemctl enable --now coldops-heal.timer
systemctl start coldops-heal.service
systemctl list-timers coldops-heal.timer --no-pager | head -3
echo "Container doctor installed. Repairs are logged to /opt/coldops/logs/heal.log"
