#!/usr/bin/env bash
# Deploy to the Pi: check locally, rsync the source, install it into the Pi's venv,
# then install and restart the systemd service.
#   deploy/deploy.sh               full deploy
#   deploy/deploy.sh --no-service  install the code only (CLI use; service untouched)
# Env: PI_HOST (default pi@kotivalo.local), SKIP_TESTS=1 skips ruff and pytest.
set -euo pipefail
cd "$(dirname "$0")/.."

PI_HOST=${PI_HOST:-pi@kotivalo.local}
REMOTE_DIR=/home/pi/kotivalo
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
  sudo install -m 644 deploy/kotivalo.service /etc/systemd/system/kotivalo.service
  sudo systemctl daemon-reload
  sudo systemctl enable -q kotivalo.service
  sudo systemctl restart kotivalo.service
  sleep 5
  systemctl --no-pager --lines=15 status kotivalo.service || true
fi
EOF
