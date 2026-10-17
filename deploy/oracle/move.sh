#!/bin/sh
# Move ColdOps from Hetzner to Oracle, run from the laptop:
#
#   sh deploy/oracle/move.sh <oracle-ip>            rehearsal (old server untouched)
#   sh deploy/oracle/move.sh <oracle-ip> --final    the real move
#
# The two servers cannot reach each other over SSH, so the kit goes via the
# laptop, which also keeps a copy under secrets/ (gitignored).
set -eu
IP=${1:?usage: move.sh <oracle-ip> [--final]}
MODE=${2:-}
KEY="$HOME/.ssh/titan_hetzner"
OLD=root@168.119.161.220
NEW=ubuntu@$IP
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
KIT="$HERE/../../secrets/oracle-move-$(date -u +%Y%m%dT%H%M%SZ)"
SSH="ssh -i $KEY -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new"
SCP="scp -q -i $KEY -o StrictHostKeyChecking=accept-new"

if ! $SSH "$NEW" 'sudo -n true'; then
    echo "cannot log in to $NEW with $KEY, or no passwordless sudo"
    exit 1
fi
if [ "$MODE" = "--final" ]; then
    # Two live stacks would send, read and warm up twice. The operator stops
    # the old one (README.md); this only checks that they did.
    busy=$($SSH "$OLD" "docker ps --format '{{.Names}}' | grep -E 'outbox|inbound|temporal-worker|browser|-api-|deploy-temporal-1' || true")
    if [ -n "$busy" ]; then
        echo "the old server is still working -- stop it first (README.md, step 4):"
        echo "$busy"
        exit 1
    fi
fi
$SCP "$HERE/pack.sh" "$OLD:/tmp/pack.sh"
$SSH "$OLD" "sh /tmp/pack.sh"
mkdir -p "$KIT"
$SCP "$OLD:/tmp/coldops-move/*" "$KIT/"
$SSH "$NEW" 'rm -rf /tmp/coldops-move && mkdir -p /tmp/coldops-move'
$SCP "$KIT"/* "$HERE/setup.sh" "$NEW:/tmp/coldops-move/"
$SSH "$NEW" "sudo sh /tmp/coldops-move/setup.sh $MODE"
echo "kit kept at $KIT"
