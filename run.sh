#!/usr/bin/env bash
set -euo pipefail

export XIAOZHI_GATEWAY_CONFIG="${XIAOZHI_GATEWAY_CONFIG:-/app/config/devices.yaml}"

if [ -f /data/options.json ]; then
  export XIAOZHI_GATEWAY_CONFIG=/config/devices.yaml
  python -m app.addon_options /data/options.json /config/devices.yaml
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8125
