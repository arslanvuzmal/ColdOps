#!/bin/sh
# Install the container doctor's timer on the host. Safe to re-run.
#
#   sh /opt/coldops/deploy/install-healing.sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p /opt/coldops/logs
install -m 0644 "$HERE/systemd/coldops-heal.service" /etc/systemd/system/coldops-heal.service
install -m 0644 "$HERE/systemd/coldops-heal.timer" /etc/systemd/system/coldops-heal.timer
install -m 0644 "$HERE/systemd/coldops-backup.service" /etc/systemd/system/coldops-backup.service
install -m 0644 "$HERE/systemd/coldops-backup.timer" /etc/systemd/system/coldops-backup.timer
systemctl daemon-reload
systemctl enable --now coldops-heal.timer coldops-backup.timer
systemctl start coldops-heal.service
systemctl list-timers coldops-heal.timer coldops-backup.timer --no-pager | head -4
echo "Container doctor and daily backup installed. Both log to /opt/coldops/logs/heal.log"
