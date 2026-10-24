#!/bin/sh
# Compile the hub's modules to .mpy (MicroPython 1.27 bytecode) in build/hub/.
#
# Why: compiling .py source on the hub needs a big burst of RAM, which makes
# MicroPython grow its heap out of the memory WiFi needs (REVIEW #36).
# main.py stays a 3-line .py stub that imports hub_app.
#
# Upload the result with:  mpremote connect $HUB cp -r build/hub/. :
# Needs mpy-cross matching the firmware: pip install --user mpy-cross==1.27.0.post2
set -e
cd "$(dirname "$0")/.."
MPY_CROSS=${MPY_CROSS:-mpy-cross}
rm -rf build/hub
mkdir -p build/hub/common
for m in hub_app game_engine mode_time_attack mode_breach storage node_registry webserver; do
    "$MPY_CROSS" -s "$m.py" -o "build/hub/$m.mpy" "hub/$m.py"
done
"$MPY_CROSS" -s common/espnow_utils.py -o build/hub/common/espnow_utils.mpy common/espnow_utils.py
ls -l build/hub build/hub/common
