#!/usr/bin/env bash
set -euo pipefail

export XIAOZHI_GATEWAY_CONFIG="${XIAOZHI_GATEWAY_CONFIG:-/app/config/devices.yaml}"
export XIAOZHI_REMOTE_TEXT_PROVIDER="${XIAOZHI_REMOTE_TEXT_PROVIDER:-wyoming}"
export XIAOZHI_WYOMING_HOST="${XIAOZHI_WYOMING_HOST:-core-piper}"
export XIAOZHI_WYOMING_PORT="${XIAOZHI_WYOMING_PORT:-10200}"

if [ -f /data/options.json ]; then
  eval "$(
    python - <<'PY'
import json
import shlex
from pathlib import Path

options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
host = options.get("piper_host", "core-piper")
port = int(options.get("piper_port", 10200))
print(f"export XIAOZHI_GATEWAY_CONFIG=/config/devices.yaml")
print(f"export XIAOZHI_REMOTE_TEXT_PROVIDER=wyoming")
print(f"export XIAOZHI_WYOMING_HOST={shlex.quote(host)}")
print(f"export XIAOZHI_WYOMING_PORT={port}")
PY
  )"

  python -m app.addon_options /data/options.json /config/devices.yaml
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8125
