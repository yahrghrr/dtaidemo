#!/usr/bin/env bash
# OPTIONAL: registers a "custom device" in Dynatrace that represents this
# 3rd-party telemetry source, so it shows up as its own entity.
# It prints the CUSTOM_DEVICE-... ID you then attach to the metrics.
#
# Usage:  ./create-custom-device.sh
# Needs an API token with the scope 'entities.write' (can be a different token
# from the one used for sending metrics).
set -euo pipefail

read -r -p "Dynatrace URL (e.g. https://abc12345.live.dynatrace.com): " DT_URL
read -r -s -p "API token with scope entities.write (hidden): " TOKEN; echo
read -r -p "Display name for the device [Vendor X telemetry ($(hostname))]: " NAME
NAME=${NAME:-"Vendor X telemetry ($(hostname))"}

DT_URL=${DT_URL%/}
DT_URL=${DT_URL/.apps.dynatrace.com/.live.dynatrace.com}

BODY=$(python3 - "$NAME" "$(hostname)" <<'EOF'
import json, sys
name, host = sys.argv[1], sys.argv[2]
print(json.dumps({
    "customDeviceId": f"dtaidemo-{host}",   # stable ID: re-running updates, doesn't duplicate
    "displayName": name,
    "type": "Vendor X telemetry source",
    "group": "dtaidemo",
    "properties": {"source": "dtaidemo", "host": host},
}))
EOF
)

RESP=$(curl -sS -w '\n%{http_code}' -X POST "$DT_URL/api/v2/entities/custom" \
  -H "Authorization: Api-Token $TOKEN" -H "Content-Type: application/json" -d "$BODY")
CODE=$(echo "$RESP" | tail -n1)
JSON=$(echo "$RESP" | sed '$d')

if [ "$CODE" != "201" ] && [ "$CODE" != "200" ] && [ "$CODE" != "204" ]; then
  echo "Dynatrace returned HTTP $CODE: $JSON"
  [ "$CODE" = "403" ] && echo "Hint: the token needs the 'entities.write' scope."
  exit 1
fi

ID=$(echo "$JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("entityId",""))' 2>/dev/null || true)
echo
echo "Custom device created/updated."
echo "Entity ID: ${ID:-'(not returned - look it up in Dynatrace: search for the display name)'}"
echo
echo "Use this ID in OpenPipeline (dt.entity.custom_device), or add it directly by putting this"
echo "line in /etc/dtaidemo/config.env and running: sudo systemctl restart dtaidemo"
echo "  EXTRA_DIMENSIONS=dt.entity.custom_device=${ID:-CUSTOM_DEVICE-XXXX}"
