#!/usr/bin/env bash
# Installs dtaidemo as a background service that starts automatically on boot.
# Usage:  sudo ./install.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo:  sudo ./install.sh"
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Installing Python 3..."
  if command -v apt-get >/dev/null; then apt-get update -y && apt-get install -y python3
  elif command -v dnf >/dev/null; then dnf install -y python3
  elif command -v yum >/dev/null; then yum install -y python3
  else echo "Could not install Python 3 automatically - please install it and re-run."; exit 1
  fi
fi

echo
echo "=== dtaidemo installer ==="
echo
if [ -f /etc/dtaidemo/config.env ]; then
  echo "Existing settings found in /etc/dtaidemo/config.env - keeping them."
  echo "(Delete that file and re-run this script if you want to enter new ones.)"
else
  echo "1) Your Dynatrace environment URL"
  echo "   Example: https://abc12345.live.dynatrace.com"
  echo "   (Copying the address from your browser, e.g. https://abc12345.apps.dynatrace.com, is fine too.)"
  read -r -p "   URL: " DT_URL
  echo
  echo "2) Your Dynatrace API token (needs the scope 'metrics.ingest'). It starts with dt0c01."
  read -r -s -p "   Token (hidden while typing): " DT_API_TOKEN
  echo
  if [ -z "$DT_URL" ] || [ -z "$DT_API_TOKEN" ]; then
    echo "URL and token are both required. Nothing was installed."; exit 1
  fi
  install -d -m 755 /etc/dtaidemo
  umask 077
  cat > /etc/dtaidemo/config.env <<EOF
# dtaidemo settings - edit, then run: sudo systemctl restart dtaidemo
DT_URL=$DT_URL
DT_API_TOKEN=$DT_API_TOKEN
# How often to send data (seconds)
INTERVAL_SECONDS=30
# A spike happens at a random time between these two values (minutes)
SPIKE_EVERY_MIN=15
SPIKE_EVERY_MAX=30
# How long each spike lasts (minutes)
SPIKE_DURATION_MIN=5
# Value of the "source" dimension (used by OpenPipeline to recognise this data)
SOURCE_NAME=dtaidemo
# true = also send a heartbeat log line each cycle (token needs logs.ingest too)
HEARTBEAT_LOGS=false
EOF
  chmod 600 /etc/dtaidemo/config.env
  umask 022
fi

install -d -m 755 /opt/dtaidemo /var/lib/dtaidemo
install -m 755 "$HERE/dtaidemo.py" /opt/dtaidemo/dtaidemo.py

# Helper command to force a spike right now
cat > /usr/local/bin/dtaidemo-spike <<'EOF'
#!/usr/bin/env bash
touch /var/lib/dtaidemo/force_spike
echo "Spike requested - it starts within ~1 second (watch with: sudo journalctl -u dtaidemo -f)"
EOF
chmod 755 /usr/local/bin/dtaidemo-spike

cat > /etc/systemd/system/dtaidemo.service <<'EOF'
[Unit]
Description=dtaidemo - simulated 3rd-party telemetry for Dynatrace
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/dtaidemo/config.env
ExecStart=/usr/bin/env python3 /opt/dtaidemo/dtaidemo.py
Restart=always
RestartSec=10
DynamicUser=yes
ReadWritePaths=/var/lib/dtaidemo

[Install]
WantedBy=multi-user.target
EOF
# DynamicUser needs to be able to delete the force_spike file
chmod 0777 /var/lib/dtaidemo

systemctl daemon-reload
systemctl enable dtaidemo >/dev/null 2>&1
systemctl restart dtaidemo

echo
echo "Installed and started. Checking the first send (about 5 seconds)..."
sleep 5
journalctl -u dtaidemo -n 5 --no-pager || true
echo
echo "If you see 'HTTP 202' above, data is reaching Dynatrace."
echo
echo "Useful commands:"
echo "  sudo journalctl -u dtaidemo -f     # watch it live (Ctrl+C to exit)"
echo "  sudo dtaidemo-spike                # force a spike right now"
echo "  sudo systemctl stop dtaidemo       # stop sending"
echo "  sudo systemctl start dtaidemo      # start again"
echo "  sudo ./uninstall.sh                # remove everything"
