#!/usr/bin/env bash
# One-time move of the Pi from the old "wakeup-light" install to "kotivalo".
# Run from the laptop, in the repo root:
#   deploy/migrate-to-kotivalo.sh rehearse   copy the live state to a temp dir on the Pi and
#                                             check the new code reads it (changes nothing)
#   deploy/migrate-to-kotivalo.sh migrate    the real move; the old service stops for ~1 min
#   deploy/migrate-to-kotivalo.sh rollback   back to the old service, if kotivalo misbehaves
#   deploy/migrate-to-kotivalo.sh cleanup    after an alarm has worked: remove the old install
# Env: PI (default: pi@kotivalo.local if it answers, else pi@wakeup-light.local),
#      SKIP_TESTS=1 skips ruff and pytest in the code deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${PI:-}" ]]; then
  PI=pi@wakeup-light.local
  ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new pi@kotivalo.local true 2>/dev/null \
    && PI=pi@kotivalo.local
fi
OLD_SVC=wakeup-light
NEW_SVC=kotivalo
OLD_STATE=/var/lib/wakeup-light
NEW_STATE=/var/lib/kotivalo
OLD_CODE=/home/pi/wakeup-light
NEW_CODE=/home/pi/kotivalo
NEW_HOSTNAME=kotivalo

on_pi() { ssh -o BatchMode=yes "$PI" "$@"; }
say() { echo "== $*"; }

deploy_code() {
  say "Installing the new code to $NEW_CODE (service untouched)"
  PI_HOST="$PI" deploy/deploy.sh --no-service
}

# Integrity of the copied database, and the new code can load it (no radio needed).
check_state() {
  on_pi "set -e
    cd '$1'
    ls -la
    sqlite3 zigbee.db 'PRAGMA integrity_check;'
    '$NEW_CODE/.venv/bin/kotivalo' --state-dir '$1' devices"
}

rehearse() {
  deploy_code
  local tmp=/tmp/kotivalo-rehearsal
  say "Rehearsal: copying the live state to $tmp/state on the Pi"
  on_pi "rm -rf $tmp && mkdir -p $tmp && cp -a '$OLD_STATE' $tmp/state"
  check_state "$tmp/state"
  on_pi "rm -rf $tmp"
  say "Rehearsal OK: nothing was changed on the Pi"
}

migrate() {
  on_pi "test -d '$OLD_STATE'" || { echo "No $OLD_STATE on the Pi: nothing to migrate"; exit 1; }
  on_pi "test ! -e '$NEW_STATE'" || { echo "$NEW_STATE already exists: refusing"; exit 1; }
  deploy_code

  say "Stopping $OLD_SVC"
  on_pi "sudo systemctl stop $OLD_SVC"
  # From here on, any failure puts the old service back.
  trap 'echo "!! Migration failed: restarting $OLD_SVC"; on_pi "sudo systemctl disable --now $NEW_SVC 2>/dev/null; sudo systemctl start $OLD_SVC"' ERR

  local backup
  backup="backups/$OLD_SVC-$(date +%Y%m%d-%H%M%S)"
  say "Backing up $OLD_STATE to $backup on the laptop (holds the Zigbee network key)"
  mkdir -p "$backup"
  rsync -a "$PI:$OLD_STATE/" "$backup/"
  test -s "$backup/zigbee.db"
  ls -la "$backup"

  say "Copying $OLD_STATE to $NEW_STATE"
  on_pi "sudo cp -a '$OLD_STATE' '$NEW_STATE'"
  check_state "$NEW_STATE"

  say "Switching services: $OLD_SVC off, $NEW_SVC on"
  on_pi "set -e
    sudo install -m 644 '$NEW_CODE/deploy/$NEW_SVC.service' /etc/systemd/system/$NEW_SVC.service
    sudo systemctl daemon-reload
    sudo systemctl disable -q $OLD_SVC
    sudo systemctl enable -q --now $NEW_SVC"

  say "Waiting for the new service to answer"
  on_pi "for i in \$(seq 1 60); do curl -sf localhost:8080/api/state >/dev/null && exit 0; sleep 2; done; exit 1"
  on_pi "systemctl is-active $NEW_SVC; curl -s localhost:8080/api/state | python3 -c 'import json,sys; s=json.load(sys.stdin); print(\"devices:\", len(s[\"devices\"]), \"| light:\", s[\"light\"][\"ieee\"])'"
  trap - ERR

  say "Hostname -> $NEW_HOSTNAME"
  on_pi "set -e
    sudo sed -i 's/^127\.0\.1\.1\s.*/127.0.1.1\t\t$NEW_HOSTNAME/' /etc/hosts
    sudo hostnamectl set-hostname $NEW_HOSTNAME
    sudo systemctl restart avahi-daemon
    hostname"
  say "Checking the new name (records its host key: same Pi, new name)"
  for _ in $(seq 1 15); do
    ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new pi@kotivalo.local \
      'echo "reachable as $(hostname).local"' && break
    sleep 2
  done

  say "Done. The old install stays until: deploy/migrate-to-kotivalo.sh cleanup"
}

rollback() {
  say "Rolling back to $OLD_SVC (its state is untouched since the migration)"
  on_pi "set -e
    sudo systemctl disable -q --now $NEW_SVC
    sudo systemctl enable -q --now $OLD_SVC
    systemctl is-active $OLD_SVC"
}

cleanup() {
  on_pi "systemctl is-active -q $NEW_SVC" || { echo "$NEW_SVC is not running: refusing"; exit 1; }
  say "Removing the old unit, code and state ($OLD_STATE is backed up under backups/)"
  ls -d backups/$OLD_SVC-* >/dev/null
  on_pi "set -e
    sudo rm -f /etc/systemd/system/$OLD_SVC.service
    sudo systemctl daemon-reload
    rm -rf '$OLD_CODE'
    sudo rm -rf '$OLD_STATE'
    ls /home/pi /var/lib | grep -E 'wakeup|kotivalo' || true"
}

case "${1:-}" in
  rehearse | migrate | rollback | cleanup) "$1" ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
