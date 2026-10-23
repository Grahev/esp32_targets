# Code review — ESP32 Targets

_Summary: written at the end of the review pass (see top section once filled in)._

<!-- SUMMARY -->

---

Findings are numbered once and keep their number. Severity:
- **Critical**: loses data or breaks the system for everyone.
- **High**: breaks a game in normal use, or blocks scaling to N nodes.
- **Medium**: wrong behaviour or fragility that players will notice sometimes.
- **Low**: polish, cleanup, docs.

Line numbers refer to the code as it was at commit `5d2ba5a` (before any fixes).

## Critical

### #1 — A power cut while saving scores can wipe the whole leaderboard
`hub/main.py:178-221` (`save_score`, `get_leaderboard`)
- **What:** The score file is rewritten in place (`open(filename, 'w')` then `json.dump`). If the hub loses power mid-write, the file is truncated or empty. On the next game, `get_leaderboard` hits the JSON error, returns `[]`, and `save_score` overwrites the file with a single new entry.
- **Why it matters:** One badly timed power-off at game end (common when packing up) destroys every stored score, with no error shown.
- **Fix:** Write to `<file>.tmp`, then `os.rename` it over the real file (atomic on LittleFS). If an existing file fails to parse, rename it to `<file>.corrupt` before starting a new list, so it's never overwritten. Move file helpers into one function.

## High

### #2 — "Stop" never puts the nodes back to Standby/Idle
`hub/main.py:297-306`
- **What:** `/stop` sets `hub.game = None` and only then calls `hub.game_over()`, which starts with `if self.game:`, so it does nothing. `sys_mode` stays 1 (Active).
- **Why:** After an abort, every node stays dark in Active mode and never returns to its idle blue. Nodes that join later are also told "Active". Only a hub reboot fixes it.
- **Fix:** Split `game_over(save=True)` into an "end game" path that `/stop` calls with `save=False` before clearing the game.

### #3 — An exception in the radio listener or game loop silently stops the game forever
`hub/main.py:310-368`, `378-390`
- **What:** `e.recv()` sits outside the `try`. `hub.game.tick()` has no `try` at all. An exception kills that uasyncio task, while the web server keeps running, so the dashboard looks alive but no hits arrive and no targets light. There is no top-level recovery: if `main()` raises, the board drops to the REPL. The listener also reads only one packet every 10 ms.
- **Why:** This is a freeze that needs a power cycle to fix, and it gives the player no clue.
- **Fix:** Guard each loop iteration with try/except plus logging, drain all pending packets each pass, and wrap `main()` so that an unexpected crash resets the board (but Ctrl-C still reaches the REPL).

### #4 — Nodes that go offline are never removed
`hub/main.py:73-120`, `hub/game_engine.py:187-247`, `428-441`
- **What:** `available_nodes` only grows. If a node's battery dies or it's switched off, it stays in the pool.
- **Why:** In Time Attack+ the dead node can be chosen as the lit target. With a minimum of 1 active target, the game then has nothing to shoot for the rest of the round. In The Breach it can be put in the sequence, which guarantees a fail. Each broadcast also unicasts to it and waits for a send timeout. This gets worse with every node added.
- **Fix:** Track `last_seen` per node, mark it offline after about 3 missed heartbeats (15 s), remove it from the pool, and tell the game mode (`on_node_lost`) and the UI. Send unicasts only to online nodes.

### #5 — Hits are sent as ESP-NOW broadcasts: no ACK, no retry
`node/main.py:104-110`, `167-174`
- **What:** The node sends HIT (and ANNOUNCE) to `ff:ff:ff:ff:ff:ff`. Broadcast frames are never acknowledged or retransmitted at the MAC layer, and `e.send` returns success regardless.
- **Why:** A hit lost to interference or a collision with another node's packet just vanishes, and the player's shot doesn't count. The chance of collisions grows with the number of nodes.
- **Fix:** The node learns the hub's MAC from the first command it receives and unicasts to it from then on. Unicast frames are ACKed and retried by the radio. `send()` returning False triggers up to 3 app-level retries, then one broadcast as a fallback.

### #6 — Node identity is a hand-edited `config.json`, and duplicates break silently
`node/main.py:20`, `34-40`; `hub/main.py:73-82`
- **What:** Each node reads `node_id` from `config.json` and defaults to 1 if the file is missing. A new node flashed without editing the file becomes a second "node 1".
- **Why:** Two nodes with the same ID overwrite each other's MAC in `node_macs` every 5 s, so commands go to whichever announced last. Every new target needs a manual file edit.
- **Fix:** The hub identifies nodes by MAC and assigns stable IDs, saved in `nodes.json`. A node can still claim an ID through `config.json` if that ID is free, which keeps existing setups unchanged. A node without a config just works.

## Medium

### #7 — No sequence number or version in the packets
`common/espnow_utils.py:9-12`
- **What:** Messages carry no sequence number and no protocol version, and use native struct alignment (`'ifiBiB'`, 21 bytes with padding).
- **Why:** Once retries exist (#5), a hit whose ACK was lost is sent again and would count twice. Format changes can't be detected.
- **Fix:** Add a v2 node message: `'<BBHHfBB'` = version, type, claimed id, seq, battery V, battery %, flags (12 bytes, explicit little-endian). The hub drops repeated `(mac, seq)`. It still accepts v1 (21-byte) packets, so old nodes keep working during an upgrade.

### #8 — Every node runs an open Wi-Fi access point
`node/main.py:44-48`
- **What:** MicroPython on the ESP8266 starts its AP (`MicroPython-edf4f4`, open) by default, and the code never turns it off. ESP-NOW packets are then sent from the AP MAC (`4a:55:19:ed:f4:f4`).
- **Why:** 10 nodes means 10 open networks next to `Airsoft-Master`, which confuses players joining the dashboard. The AP's beacons also drain the node's battery.
- **Fix:** Call `network.WLAN(network.AP_IF).active(False)` at boot.

### #9 — Idle node reads the ADC and rewrites the LED every 10 ms
`node/main.py:145-158`
- **What:** In Idle mode each loop pass calls `read_battery()` (ADC) and `set_led()` (bit-banged NeoPixel, interrupts off).
- **Why:** Reading the ADC very often while Wi-Fi is on is a known cause of radio dropouts on the ESP8266. It also wastes power.
- **Fix:** Cache the battery reading and refresh it every 2 s. Write the LED only when the colour changes.

### #10 — Node main loop has no error handling
`node/main.py:116-187`
- **What:** Any exception (an OSError from `e.send`/`e.recv`, a bad packet) ends `main()`, and the target goes dead until it's power-cycled.
- **Fix:** Wrap each pass in try/except. If errors repeat, reset the node.

### #11 — Blocking sleeps on the hub's event loop
`hub/game_engine.py:363` (`time.sleep(0.1)`), `467` (`time.sleep_ms(100)`)
- **What:** These sleeps run inside `tick()`, which runs on the uasyncio loop.
- **Why:** For 100 ms the hub doesn't read radio packets or serve the web UI. Hits that arrive then are timestamped late, which skews reaction times.
- **Fix:** Remove them. The blink they create is cosmetic and can be scheduled with a state or timestamp.

### #12 — Time Attack+ re-lights the target that was just hit, and spawns with no delay
`hub/game_engine.py:187-203`, `310-331`
- **What:** On a hit, the same node is queued to re-activate after the delay, while `scheduler_tick` also spawns a replacement immediately.
- **Why:** This breaks the PRD's "no-repeat" and "spawn delay" rules (`docs/FEATURE_TIME_ATTACK_PRD.md` §5.1–5.2). The number of lit targets drifts above the difficulty's minimum, and with N nodes the same few targets keep recurring.
- **Fix:** After a hit, set `next_spawn_at = now + stage_delay`. The scheduler spawns a different node (weighted by how often each node has been used) once the delay has passed. With a single node, the same node is allowed after the delay.

### #13 — The Breach's precision bonus compounds across levels
`hub/game_engine.py:654`
- **What:** `self.score = int(self.score * 1.2)` multiplies the running total at every cleared level, not just that level's points.
- **Why:** Scores grow as 1.2^levels, so early levels count more than late ones and the leaderboard doesn't reflect skill.
- **Fix:** Compute the level's points (100 + time bonus) × 1.2 and add that to the total.

### #14 — A browser that vanishes keeps its socket, and send tasks pile up
`hub/main.py:53-59`, `234-266`
- **What:** When a phone sleeps, its TCP connection isn't closed. `broadcast_ws` keeps spawning one `send` task per message, and each one blocks once the socket buffer is full, until lwIP gives up minutes later.
- **Why:** RAM fills up with stuck tasks. With N nodes there are more messages (battery updates every 5 s per node), so this happens faster.
- **Fix:** Send with a timeout (`asyncio.wait_for`), and drop the client on its first failure.

### #15 — Start/stop requests fail silently
`hub/main.py:269-295`, `hub/static/index.html:666-685`
- **What:** With no nodes, `/start` returns the text "No Nodes Connected", but the UI ignores the response. A bad parameter (`duration=abc`) raises ValueError and the browser gets an HTTP 500. Starting while a game is running replaces it without stopping the old one.
- **Fix:** Validate the parameters, stop any running game first, return an HTTP status, and have the UI log the reply.

### #16 — The test suite is stale
`tests/`
- **What:** `test_time_attack.py` imports `TimeAttack`, which no longer exists. `test_protocol.py` uses an old `pack_message` signature. Only two of the four scripts run.
- **Fix:** Replace them with a runnable suite (`python3 -m unittest`) covering the protocol, the scores file, node tracking and both game modes with several simulated nodes.

### #17 — No crash recovery or watchdog
`hub/main.py:378-390`, `node/main.py:189-190`
- **What:** If either program crashes, the board sits at the REPL until someone power-cycles it.
- **Fix:** Add a top-level try/except that resets the board after an unexpected crash. A hardware `machine.WDT` is a separate decision (see "needs discussion"): on ESP32 it can't be stopped once started, so it would reset the hub in the middle of `mpremote` file transfers.

### #18 — ESP-NOW peer table limit (~20) isn't handled
`hub/main.py:79`
- **What:** `add_peer` errors are swallowed. ESP-NOW allows about 20 peers, including the broadcast peer. Peers for nodes that went offline are never removed.
- **Why:** Over a long session, or with more than 19 targets, new nodes register but can't receive commands.
- **Fix:** Remove the peer when a node goes offline, and log a clear error when the table is full.

## Low (not fixed in this pass, listed for you)

- **#19** `game_engine.py:112`: the timer is broadcast when `remaining % 1000 < 150` on a 100 ms tick, so it can skip or double a second. Send it when the whole-second value changes.
- **#20** `game_engine.py:572-605`: in The Breach, a correct hit turns the node green and it stays green until the next level. The PRD says "flash green, then off".
- **#21** `game_engine.py:465`: `countdown_step % 1 == 0` is always true (dead condition).
- **#22** Dead code and unused imports: the legacy 4-field branch in `main.py:345-357` (it can never match), `with_websocket`, `Pin`, `GameMode`, `init_espnow` on the node, the unused `ESPNOW_PMK`, `hub.nodes`, and the duplicate `self.available_nodes = []` (`main.py:30-31`).
- **#23** `node/main.py:76-87`: battery calibration is a placeholder, and `charging = voltage > 4.25` can never be true with a 4.2 V full scale.
- **#24** `main.py:194-200`: The Breach saves `hits: 0` and `avg_rt: 0` and records 0-point games, so its leaderboard is mostly zero rows.
- **#25** Config is scattered: channel 1 is hard-coded in the node and hub instead of using `WIFI_CHANNEL`, plus the SSID, colours, timings and thresholds. A single `config` module would help.
- **#26** `main.py:113-114`: `on_hit` calls `register_node`, which re-sends SET_MODE on every hit.
- **#27** `node/main.py:143`: nodes print "Unpack fail" for every other node's broadcast. They should ignore packets that aren't commands.
- **#28** Security: the AP is open and ESP-NOW is unencrypted, so anyone in range can start or stop games or spoof hits. This is acceptable for a private field, but worth knowing.
- **#29** The docs (`README.md`, `docs/SETUP_GUIDE.md`, `docs/USER_MANUAL.md`, `prd.md`) describe ESP32-S2 nodes, Zombie mode, a pairing button and "tap each node to sync". None of these match the code.
- **#30** Reaction time is measured on the hub, from sending the LED command to receiving the hit, so it includes the radio delay both ways (a few ms). It could be timestamped on the node.
- **#31** `hub/lib/microdot_websocket.py:30`: when it answers a PING, `self.send(send_opcode, data)` has its arguments swapped, so a client ping would crash that socket. Browsers don't normally send pings.
- **#32** `.pyc` files were committed and there was no `.gitignore` (fixed during setup).
- **#33** `game_engine.py:170-171`: `freeze_end_time` and `global_mask_end_time` are only created in `start_game_play`, not in `__init__`. This is safe today thanks to the state check, but fragile.
- **#34** Hardware: the node's LED is on GPIO0 (D3), a boot strapping pin. If the LED's data line is held low at power-up, the ESP8266 boots into flash mode. It works now, but GPIO4 (D2) would be safer on new nodes.
- **#35** `scores_time_attack.json` on the hub is an orphan in the old format. The code never reads it. Deleting it is your call.

## Needs discussion
_(filled in during the fix phase)_
