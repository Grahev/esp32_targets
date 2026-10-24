# Feature proposals

These are ideas only; none of them is built. Effort: **S** = an evening, **M** = a weekend, **L** = several weekends. "Multi-node" says whether the feature needs more than one node to make sense.

⭐ marks my top 3 picks: cheap to build, and each one gets more valuable as you add targets.

| # | Feature | Effort | Extra hardware | Multi-node |
|---|---------|:------:|----------------|:----------:|
| 1 ⭐ | Identify a node from the dashboard | S | none | useful from 2 |
| 2 ⭐ | Player names and per-player stats | S–M | none | no |
| 3 ⭐ | Shoot / No-Shoot mode | S–M | none | yes (≥2) |
| 4 | Team duel mode | M | none | yes (≥4) |
| 5 | Zombie survival mode (from the original PRD) | M | none | works with 1, better with more |
| 6 | Drill mode with par times | M | none | yes |
| 7 | Sensitivity / calibration mode | S–M | none | no |
| 8 | Sound effects | S–M | piezo buzzer per node or on the hub | no |
| 9 | Battery calibration and low-battery alerts | S | multimeter, once | no |
| 10 | Statistics page (per-target heatmap, history) | M | none | most useful with N |
| 11 | OTA updates for nodes over ESP-NOW | L | none | yes, matters at 5+ |
| 12 | Hub start button and status LED | S | button + LED on hub GPIO | no |
| 13 | One-command build and deploy (`.mpy`) | S | none | helps at N |
| 14 | Signed / encrypted radio | S–M | none | no |

---

### 1. ⭐ Identify a node from the dashboard
- **What:** an "identify" button next to each node in the Battery view. The hub sends that node a command to blink white 5 times. The reverse also works: tap a target and the dashboard highlights its ID.
- **Why:** once there are 6+ targets in a field, "which one is node 4?" is the first question every time. The hub already has unicast commands, so this needs a new `CMD_BLINK` and a small change on the node.
- **Hardware:** none.

### 2. ⭐ Player names and per-player stats
- **What:** enter a name (or pick a recent one) before pressing Start. The name is saved with the score, and the leaderboard shows names instead of `OP_100`. A player page shows best score, average reaction time and trend.
- **Why:** this is what makes people come back. The data already exists (`avg_rt`, `max_combo`, `penalties`); only the name is missing. Data goes in a new `players.json`, using the atomic save from REVIEW #1.
- **Hardware:** none.

### 3. ⭐ Shoot / No-Shoot mode
- **What:** targets light **red = shoot** or **green = hostage, don't shoot**. Hitting green costs a lot of points and the combo. The share of green rises with difficulty, and some targets switch colour while lit.
- **Why:** this trains decision-making, not just speed, and it reuses the Time Attack+ scheduler. It needs at least 2 nodes, and gets better with more.
- **Hardware:** none.

### 4. Team duel mode
- **What:** two players or teams. Nodes are split into a red half and a blue half, both lit at once. Each side races to clear its own colour, and hitting the other side's colour gives them a point.
- **Why:** head-to-head play is the most fun format for groups. It needs 4+ nodes.

### 5. Zombie survival mode
- **What:** a lit target slowly grows brighter, and if it reaches full brightness you're "bitten". Waves get faster. This was in the original PRD and user manual but never built.
- **Why:** it's a different kind of pressure from Time Attack. It needs a brightness ramp (repeated LED commands, or a new `CMD_FADE` so the node ramps by itself).

### 6. Drill mode with par times
- **What:** saved courses such as "1 → 3 → 2 → 4, par 4.0 s", shown as a list on the dashboard. The score is the time against par, and penalties come from wrong targets.
- **Why:** this is how real shooting practice works: repeatable drills you can compare week to week.

### 7. Sensitivity / calibration mode
- **What:** a mode where every sensor trigger is logged live per node, with no game running. You tap or shoot each target and see whether it registers once, twice or not at all. A per-node debounce time can be set from the dashboard.
- **Why:** SW-420 modules vary a lot. A target that double-triggers or misses BBs ruins the scoring, and right now the only fix is turning the potentiometer blind.

### 8. Sound effects
- **What:** a piezo buzzer beeps on a hit, on start and on game over, either on the hub (one sound for everyone) or on each node (localised feedback).
- **Why:** players can't watch an LED and a phone while shooting. Sound fixes that.
- **Hardware:** piezo buzzer (cheap). On the node there are free pins, such as D2/GPIO4 or D5.

### 9. Battery calibration and low-battery alerts
- **What:** measure each node's battery once with a multimeter and enter the reading in the dashboard to set its scale factor. The dashboard warns "Node 3 at 15%" before a game starts.
- **Why:** the current reading is a placeholder (REVIEW #23), so the percentage isn't trustworthy, and a node dying mid-game is the most likely real failure.

### 10. Statistics page
- **What:** per-target average reaction time ("node 7 is your slow side") and hits and misses per node, plus a score history chart.
- **Why:** it turns games into training feedback. It needs per-hit records stored, but kept small.

### 11. OTA updates for nodes over ESP-NOW
- **What:** the hub sends a new `main.py` to every node in chunks over ESP-NOW (checksum, then write to a temp file, rename, reboot). The dashboard shows each node's firmware version.
- **Why:** updating 10 nodes over USB one by one is painful, and mixed versions cause bugs. The v2 packet already has a version byte to build on.
- **Effort:** L. Chunking, retries and a safe rollback are needed so a bad transfer can't brick a node.

### 12. Hub start button and status LED
- **What:** a physical button on the hub starts the last-used game, and an LED shows the hub's status (booting / ready / game running).
- **Why:** you can start a round without unlocking a phone, and you can see that the hub is alive.

### 13. One-command build and deploy
- **What:** `tools/deploy.py hub|node` compiles modules to `.mpy`, uploads only what changed, never touches `scores_*.json` or `nodes.json`, resets in the right order and checks the boot log.
- **Why:** it makes every change safer and faster, and it's the natural place to fix the memory issue (REVIEW #36).

### 14. Signed / encrypted radio
- **What:** ESP-NOW encryption, or a shared-secret signature in the packet.
- **Why:** anyone nearby with an ESP board can fake hits today (REVIEW #28). That doesn't matter for friendly games, but it does for competitions. ESP32 limits the number of encrypted peers, so check that against the node count first.
