#!/usr/bin/env bash
# One-time, idempotent system setup for the kotivalo Pi. Runs as root; on a fresh Pi:
#   ssh pi@raspberrypi.local 'sudo bash -s' < deploy/pi-setup.sh
# Afterwards the Pi is pi@kotivalo.local (choose another name with NEW_HOSTNAME=...).
# Ends with a reboot unless run with REBOOT=0 ('sudo REBOOT=0 bash -s').
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt_opts=(-y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
NEW_HOSTNAME=${NEW_HOSTNAME:-kotivalo}

echo "== Hostname $NEW_HOSTNAME (reachable as $NEW_HOSTNAME.local via avahi/mDNS)"
if [[ -d /etc/cloud/cloud.cfg.d ]]; then
  # Pi OS runs cloud-init on every boot; without this it may reset the hostname.
  echo "preserve_hostname: true" > /etc/cloud/cloud.cfg.d/99-preserve-hostname.cfg
fi
hostnamectl set-hostname "$NEW_HOSTNAME"
if grep -q "^127\.0\.1\.1" /etc/hosts; then
  sed -i "s/^127\.0\.1\.1\s.*/127.0.1.1\t\t$NEW_HOSTNAME/" /etc/hosts
else
  printf '127.0.1.1\t\t%s\n' "$NEW_HOSTNAME" >> /etc/hosts
fi
systemctl try-restart avahi-daemon

echo "== Packages"
apt-get update -q
apt-get "${apt_opts[@]}" full-upgrade
apt-get "${apt_opts[@]}" install python3-venv sqlite3 iw
apt-get "${apt_opts[@]}" autoremove

echo "== Wi-Fi power saving off (a headless Pi otherwise drops off the network)"
cat > /etc/NetworkManager/conf.d/wifi-powersave-off.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF
# Apply now without re-activating the connection, which would cut this SSH session.
iw dev wlan0 set power_save off || true

echo "== Volatile journal (spares the SD card; logs no longer survive a reboot)"
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/volatile.conf <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=30M
EOF
systemctl restart systemd-journald

echo "== Hold time-sync.target until NTP syncs, but give up after 3 min without internet"
mkdir -p /etc/systemd/system/systemd-time-wait-sync.service.d
cat > /etc/systemd/system/systemd-time-wait-sync.service.d/timeout.conf <<'EOF'
[Service]
TimeoutStartSec=3min
EOF
systemctl daemon-reload
systemctl enable -q systemd-time-wait-sync.service
systemctl is-active --quiet systemd-timesyncd || echo "WARNING: systemd-timesyncd is not active"

echo "== Keep USB-serial probers away from the XBee"
for svc in ModemManager brltty; do
  if systemctl cat "$svc.service" >/dev/null 2>&1; then
    systemctl disable --now "$svc.service"
  fi
done

echo "== State directory"
install -d -o pi -g pi -m 0750 /var/lib/kotivalo

if [[ "${REBOOT:-1}" == 1 ]]; then
  echo "== Rebooting"
  systemctl reboot
fi
