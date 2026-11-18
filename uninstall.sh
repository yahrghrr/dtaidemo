#!/usr/bin/env bash
# Removes dtaidemo completely.  Usage:  sudo ./uninstall.sh
set -u
if [ "$(id -u)" -ne 0 ]; then echo "Please run with sudo:  sudo ./uninstall.sh"; exit 1; fi
systemctl disable --now dtaidemo 2>/dev/null
rm -f /etc/systemd/system/dtaidemo.service /usr/local/bin/dtaidemo-spike /usr/local/bin/dtaidemo-set-service
rm -rf /opt/dtaidemo /var/lib/dtaidemo /etc/dtaidemo
systemctl daemon-reload
echo "dtaidemo removed."
