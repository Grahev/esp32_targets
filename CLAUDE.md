# ESP32 Targets — MicroPython game project

Repo: https://github.com/Grahev/esp32_targets
Language: MicroPython (not Arduino, not ESP-IDF, not PlatformIO).
Main tool for talking to the boards: `mpremote`. Use `esptool.py` only for chip info.

## Hardware

Two boards are connected to this machine over USB: an ESP32 (HUB) and an ESP8266 Wemos D1 Mini (NODE).

| Role | USB chip | Stable device path |
|------|----------|--------------------|
| HUB (ESP32, main board, runs the game) | CP210x (10c4:ea60) | `/dev/serial/by-id/usb-Silicon_Labs_*` |
| NODE (ESP8266, target) | CH340 (1a86:7523) | `/dev/serial/by-id/usb-1a86_*` |

- Always use the `/dev/serial/by-id/` paths. Never hardcode `/dev/ttyUSB0` or `/dev/ttyUSB1`, because they can swap after a reboot or replug.
- At the start of a session, run `ls -l /dev/serial/by-id/` to confirm both boards are present.
- If a board is missing, stop and tell me. Don't try to fix USB or driver issues yourself.

Shortcuts to use in commands:

```bash
HUB=$(ls /dev/serial/by-id/usb-Silicon_Labs_* | head -1)
NODE=$(ls /dev/serial/by-id/usb-1a86_* | head -1)
```

## Files on the HUB board (current state)

```
boot.py
main.py                  # entry point, runs on boot
game_engine.py           # core game logic
common/                  # shared code (hub + node)
hub/                     # hub-specific code
lib/                     # libraries
scores_TheBreach.json    # LIVE DATA — high scores
scores_TimeAttack.json   # LIVE DATA — high scores
scores_time_attack.json  # LIVE DATA — high scores (possibly an old duplicate, ask before deleting)
```

On first use, read the code and add a short "How the project works" section below, describing how the hub and nodes communicate.

## How the project works

Airsoft reaction-target game. One HUB runs the game and a web UI. One or more NODES are targets, each with a vibration sensor and one WS2812 LED.

**Boards.** The HUB is an ESP32 (`ESP32_GENERIC`, MicroPython 1.27). The NODE is actually an **ESP8266** (Wemos D1 Mini, `ESP8266_GENERIC`, MicroPython 1.27), not an ESP32. It has the SW-420 sensor on GPIO5 (D1), the NeoPixel on GPIO0 (D3) and battery sensing on ADC(0). Its ID comes from `config.json` (`{"node_id": N}`).

**Radio: ESP-NOW on WiFi channel 1.** The packet formats live in `common/espnow_utils.py`, which both boards share:
- Node → Hub: `struct 'ifiBiB'` = `(node_id, batt_v, batt_pct, hit, msg_type, charging)`. `msg_type` is 0 = HIT or 1 = ANNOUNCE.
  - Nodes send everything to the broadcast MAC `ff:ff:ff:ff:ff:ff`, so they don't need to know the hub's MAC.
  - Each node sends an ANNOUNCE at boot and then every 5 s. It sends a HIT on each sensor IRQ (300 ms debounce), whatever mode it is in.
- Hub → Node: `struct 'iBBB'` = `(cmd, a, b, c)`.
  - `cmd 1` = set the LED to `(r, g, b)`. The node only applies it in mode 1.
  - `cmd 2` = set the mode to `a`: 0 Idle (dim blue, pulsing when battery <10%), 1 Active (game), 2 Standby (LED off).
  - Commands go out as a broadcast plus a unicast to every known node MAC.

**Hub (`main.py`).** It runs uasyncio with three tasks:
1. `espnow_listener`: STA interface, polls every 10 ms. An ANNOUNCE calls `register_node`, which records the ID → MAC, adds the node as a peer and to `available_nodes`, stores the battery level and unicasts the current mode to that node. A HIT calls `on_hit`, which passes it to `hub.game.on_hit(node_id)`.
2. `game_loop`: calls `hub.game.tick()` every 100 ms.
3. A Microdot web server on the open AP `Airsoft-Master` at 192.168.4.1:
   - `/` serves `hub/static/index.html`.
   - `/start?mode=TimeAttack|TheBreach&…` and `/stop` start and stop games.
   - `/api/leaderboard?mode=` returns the leaderboard.
   - `/ws` is a WebSocket that pushes `status`, `hit`, `score`, `timer`, `battery` and `leaderboard` messages to the browser.

**Game flow (`game_engine.py`).** The game modes are `TimeAttackPlus` and `TheBreach`. Both are `GameMode` state machines. They drive LEDs through `hub.send_node_cmd`/`broadcast_led` and the UI through `broadcast_ws`. When a game starts, the hub puts the nodes in mode 1 (Active). At game over, it saves the score to `scores_<TimeAttack|TheBreach>.json` (top 20), switches the nodes to mode 2 (Standby), then to mode 0 (Idle) after 10 s. `scores_time_attack.json` is not referenced by the code. It has an older score format (`hpm`/`hps` fields), so it's left over from an earlier version.

**Game modes.**
- **Time Attack+** (`TimeAttackPlus`): runs for a set time. Yellow ×3 then green start sequence. A red node is a live target, and a hit scores 10/5/2 points by reaction time (<750 / ≤1400 / >1400 ms), ×1.5 once the combo passes 3. A hit on a dark node costs −15 and freezes all nodes orange for 1 s. The minimum number of lit targets rises every 30 s, depending on difficulty (`DifficultyConfig`).
- **The Breach** (`TheBreach`): a memory game with 10 levels. Nodes flash a blue sequence (3 → 9 long), and the player hits them in order. A wrong node or a gap of more than 5 s fails the level and ends the game. Each level adds +100 plus a time bonus against par (2 s per target).

**Hardware actually used.** Node: SW-420 vibration sensor (digital, rising-edge IRQ), 1× WS2812 on GPIO0 and battery voltage on A0. Hub: only the radio and WiFi, with no GPIO, buttons or display. Neither board uses buttons or displays. The PRD mentions a pairing button, but it isn't implemented.

**Radio details.** The structs use native alignment: the node message is 21 bytes and the command is 7 bytes on ESP32, ESP8266 and the PC alike. The ESP8266 node also keeps its default open AP (`MicroPython-xxxxxx`) active, and its ESP-NOW packets come from its **AP** MAC (`4a:55:…`), not its STA MAC.

**Board-only files.** `boot.py` on both boards is the MicroPython default (the node's version only adds `gc.collect()`). The `scores_*.json` files exist only on the hub. Repo-only: `docs/`, `tests/`, `prd.md`, `README.md`. The PRD and docs describe an older design (ESP32-S2 nodes, Zombie mode, pairing button) that the code doesn't follow.

**Repo path → board path.** The repo layout is not the same as the board layout:

| Repo | Board |
|------|-------|
| `hub/main.py`, `hub/game_engine.py` | HUB `:main.py`, `:game_engine.py` |
| `hub/lib/*.py` | HUB `:lib/` |
| `hub/static/index.html` | HUB `:hub/static/index.html` |
| `node/main.py`, `node/config.json` | NODE `:main.py`, `:config.json` (config is per node, so keep each node's ID) |
| `common/espnow_utils.py` | both boards, `:common/espnow_utils.py` |

Upload hub files one by one, using the paths in the table. The board copies use CRLF line endings, but their content matches the repo as of commit 5d2ba5a.

## Commands

All commands that stream output or open a REPL **must** be wrapped in `timeout`, or they will hang forever.

Any `mpremote` command (`ls`, `cat`, `cp`, `exec`) stops the running `main.py`, and it stays stopped until a reset. **Always reset the board afterwards** (node first, then hub). `mpremote repl` fails in a non-interactive shell (termios error), so read the boot log with `timeout 20 python3 tools/serial_log.py $HUB 12 --reset` instead.

```bash
# List files on a board
mpremote connect $HUB ls
mpremote connect $NODE ls

# Read a file from a board
mpremote connect $HUB cat main.py

# Upload a single file (repo paths differ from board paths, see the table above)
mpremote connect $HUB cp hub/game_engine.py :game_engine.py
mpremote connect $HUB cp hub/main.py :main.py
mpremote connect $HUB cp hub/static/index.html :hub/static/index.html
mpremote connect $NODE cp node/main.py :main.py

# Upload a folder (creates/overwrites files inside it)
mpremote connect $HUB cp -r common :
mpremote connect $NODE cp -r common :
mpremote connect $HUB cp hub/lib/*.py :lib/
# Never `cp -r hub :` (it would put main.py at :hub/main.py)

# Run a script from the PC without saving it to the board (good for quick tests)
timeout 30 mpremote connect $NODE run test_script.py

# Reset the board and watch its output for 20 seconds
timeout 20 mpremote connect $HUB reset + repl

# Download everything from a board (backup)
mpremote connect $HUB cp -r : ./backup_hub/
```

Only one program can use a serial port at a time. If you get "port is busy", something else (another mpremote, a REPL) still has it open.

## Workflow

1. Edit the files in this repo, never directly on the board.
2. Upload only the files you changed.
3. Reset the board and read its output with `timeout` to check it works.
4. When hub and node both need to change, upload to both, then reset the node first and the hub second.
5. When a change works, commit it with a clear message. Don't push unless I ask.

## Rules — do not break these

- **Never overwrite or delete `scores_*.json` on the board.** They hold real game scores. Never upload the repo's copies of them.
- **Never run `esptool erase_flash`, `write_flash`, or reflash MicroPython** without asking me first.
- **Never delete files on a board** (`mpremote rm`) without asking me first.
- Before a large change, back up the affected board to `./backup_hub/` or `./backup_node/`. These folders are in `.gitignore`.
- Keep memory use low: both boards have limited RAM (the ESP8266 node even less than the ESP32). Avoid big imports and large strings, and prefer `const()` for constants.
- Don't add libraries that aren't available for MicroPython.
- If you're unsure which board a change belongs on, ask me.

## Environment notes

- Linux VM on Proxmox; the boards are passed through by USB vendor/device ID.
- `mpremote` and `esptool.py` live in `~/.local/bin`.
- esptool is version 4.x, so use `esptool.py` and `chip_id` (underscore), not `esptool` / `chip-id`.
