# Adding a node

A new target needs no code changes and no `config.json`. The hub sees its MAC address, gives it the next free ID, and the node saves that ID itself.

## 1. Parts and wiring (Wemos D1 Mini, ESP8266)

| Part | Connect to | Notes |
|------|------------|-------|
| SW-420 vibration sensor, digital out | **D1 / GPIO5** | Power the module from 3V3 |
| WS2812B LED, data in | **D3 / GPIO0** | 5 V or 3V3 power. GPIO0 is a boot pin: if the LED holds it low at power-up, the board starts in flash mode. If that happens, wire to D2 / GPIO4 and change `LED_PIN` in `node/main.py` (it affects every node using that firmware). |
| LiPo battery, through a divider | **A0** | The firmware reads 1024 = 4.2 V. Calibration is a placeholder (see REVIEW #23). |

## 2. Flash MicroPython (new board only)

Use the same version as the other boards: **MicroPython 1.27, `ESP8266_GENERIC`**, from https://micropython.org/download/ESP8266_GENERIC/.

```bash
NEW=/dev/serial/by-id/usb-1a86_...        # the new board; check with: ls -l /dev/serial/by-id/
esptool.py --port $NEW erase_flash
esptool.py --port $NEW --baud 460800 write_flash --flash_size=detect 0 ESP8266_GENERIC-v1.27.0.bin
```

Only do this to the **new** board. If the new board uses the same USB chip as the existing node (CH340), the `usb-1a86_*` pattern in CLAUDE.md matches both. Unplug the existing node while you work, or use the full path from `ls -l /dev/serial/by-id/`.

## 3. Upload the node code

From the repo root:

```bash
mpremote connect $NEW mkdir :common
mpremote connect $NEW cp common/espnow_utils.py :common/espnow_utils.py
mpremote connect $NEW cp node/main.py :main.py
```

Don't upload `node/config.json`. Without it, the hub assigns the lowest free ID. You only need it to ask for a specific ID (`{"node_id": 7}`), which the hub grants if no other node has that ID.

## 4. Power it up near the hub

1. The hub must be running. Reset the new node, or power-cycle it.
2. The node boots with a dim blue LED (Idle) and announces itself. Within a second the hub registers it:
   - Hub log: `New node 485519xxxxxx -> ID 4`, then `Node 4 online`.
   - Node log: `Hub found`, then `Hub assigned ID 4` (saved to the node's `config.json`).
   - Dashboard: `Node 4 Joined` in the log, and `NODE_4` in the Battery view.
3. Write the ID on the target. To read it back later: `mpremote connect $NEW cat config.json`.

To watch the logs:
```bash
timeout 15 python3 tools/serial_log.py $NEW 10 --reset
timeout 15 python3 tools/serial_log.py $HUB 10 --reset
```

## 5. Check it works

- Start a Time Attack game from the dashboard. The new node should light red sometimes and score when hit.
- Battery view: the node shows a voltage. If it's dimmed and says OFFLINE, the hub hasn't heard from it for 15 s.

## Renumbering or retiring nodes

- IDs are stored on the hub in `nodes.json` (`{"<mac hex>": id}`). To renumber, edit that file on the hub and reboot the hub. The node gets its new ID automatically within 5 s. To free the ID of a node you've retired, delete its line.
- A node that's switched off just goes offline. Its ID stays reserved for it.

## Limits

- **At most 19 nodes online at once.** ESP-NOW allows about 20 peers, and the broadcast address uses one.
- All boards must use WiFi channel 1 (`WIFI_CHANNEL` in `common/espnow_utils.py`).
- Range is roughly 50 m in the open. The node prints `Hub did not ACK` when it's at the edge.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Never joins | Hub not running, wrong MicroPython version (needs 1.27), or `common/espnow_utils.py` missing on the node |
| Joins, then drops out every ~15 s | Weak signal or a flat battery; the node's log shows `Hub did not ACK` |
| Got an unexpected ID | Its claimed ID was taken, or the hub already knew its MAC; see `nodes.json` |
| Board keeps booting into the flasher | LED data line pulling GPIO0 low; see the wiring note above |
