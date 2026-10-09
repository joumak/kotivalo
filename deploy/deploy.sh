#!/usr/bin/env bash
# Deploy to the Pi: check locally, rsync the source, install it into the Pi's venv,
# then install and restart the systemd service.
#   deploy/deploy.sh               full deploy
#   deploy/deploy.sh --no-service  install the code only (CLI use; service untouched)
# Env: PI_HOST (default pi@raspberrypi.local), SKIP_TESTS=1 skips ruff and pytest.
set -euo pipefail
cd "$(dirname "$0")/.."

PI_HOST=${PI_HOST:-pi@raspberrypi.local}
REMOTE_DIR=/home/pi/wakeup-light
service=1
[[ "${1:-}" == "--no-service" ]] && service=0

if [[ "${SKIP_TESTS:-0}" != 1 ]]; then
  .venv/bin/ruff check .
  .venv/bin/pytest -q
fi

rsync -az --delete --exclude-from=deploy/rsync-exclude ./ "$PI_HOST:$REMOTE_DIR/"

ssh "$PI_HOST" SERVICE="$service" REMOTE_DIR="$REMOTE_DIR" 'bash -s' <<'EOF'
set -euo pipefail
cd "$REMOTE_DIR"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
fi
.venv/bin/pip install -q -e .

if [[ "$SERVICE" == 1 ]]; then
  sudo install -m 644 deploy/wakeup-light.service /etc/systemd/system/wakeup-light.service
  sudo systemctl daemon-reload
  sudo systemctl enable -q wakeup-light.service
  sudo systemctl restart wakeup-light.service
  sleep 5
  systemctl --no-pager --lines=15 status wakeup-light.service || true
fi
EOF
