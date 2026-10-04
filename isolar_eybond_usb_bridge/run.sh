#!/usr/bin/with-contenv bashio
set -euo pipefail
export SERIAL_DEVICE="$(bashio::config 'serial_device')"
export SERIAL_BAUD="$(bashio::config 'serial_baud')"
export HA_HOST="$(bashio::config 'ha_host')"
export HA_PORT="$(bashio::config 'ha_port')"
export COLLECTOR_PN="$(bashio::config 'collector_pn')"
export LOG_LEVEL="$(bashio::config 'log_level')"
export DATA_DIR=/data
args=()
if bashio::config.true 'allow_remote_redirect'; then
    args+=(--allow-remote-redirect)
fi
exec python3 /app/bridge.py "${args[@]}"
