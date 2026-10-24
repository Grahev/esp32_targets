#!/usr/bin/env bash
# Build and flash v2. Never touches the hub's data (LittleFS holds settings,
# targets and scores; firmware uploads don't write that partition).
#
#   tools/deploy.sh test          host tests (node + hub) and web type check
#   tools/deploy.sh node          build + flash the node on USB
#   tools/deploy.sh hub           build the web app into the firmware, build + flash the hub
#   tools/deploy.sh all           tests, node, then hub (the order to flash both)
#   tools/deploy.sh build         build everything, flash nothing (bins in .pio/build/*/firmware.bin)
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

port() { ls /dev/serial/by-id/$1 2>/dev/null | head -1; }
HUB=$(port 'usb-Silicon_Labs_*' || true)
NODE=$(port 'usb-1a86_*' || true)

tests() {
  (cd firmware/node && pio test -e native)
  (cd firmware/hub && pio test -e native)
  (cd web && npm run typecheck)
}

node_fw() {
  [ -n "$NODE" ] || { echo "Node not connected (no /dev/serial/by-id/usb-1a86_*)"; exit 1; }
  (cd firmware/node && pio run -e node -t upload --upload-port "$NODE")
}
hub_fw() {
  [ -n "$HUB" ] || { echo "Hub not connected (no /dev/serial/by-id/usb-Silicon_Labs_*)"; exit 1; }
  (cd web && npm run build)
  (cd firmware/hub && pio run -e hub -t upload --upload-port "$HUB")
  timeout 20 python3 tools/serial_log.py "$HUB" 12 --reset | tr -d '\r' | grep -a -E '^\[|Ready|AP |SAFE' || true
}

case "${1:-}" in
  test) tests ;;
  node) node_fw ;;
  hub) hub_fw ;;
  all) tests; node_fw; hub_fw ;;
  build)
    (cd web && npm run build)
    (cd firmware/node && pio run -e node)
    (cd firmware/hub && pio run -e hub)
    ls -la firmware/node/.pio/build/node/firmware.bin firmware/hub/.pio/build/hub/firmware.bin ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
