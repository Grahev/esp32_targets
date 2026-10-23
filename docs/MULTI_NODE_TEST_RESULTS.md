# Multi-node test results

Only one real node exists so far. Multi-node behaviour was tested three ways:

1. **`tools/fake_nodes.py`** runs on the PC. The real hub code (`main.py`, `game_engine.py`, `node_registry.py`, the v2 packet format) runs against N simulated nodes on a virtual clock, with 2% radio loss.
2. **PC unit tests** (`python3 -m unittest discover -s tests`, 39 tests): both game modes with up to 10 nodes, plus hub registration, duplicates and offline handling.
3. **Real hardware** with the one node, using `tools/hub_harness.py` and `tools/node_fake_hit.py`.

## Simulation scenario (`tools/fake_nodes.py`)

Nodes boot 0.7 s apart with no `config.json`. Then a 2-minute Time Attack+ game on Hard is played. 30 s into the game one node loses power (it stops sending, and its radio doesn't ACK), and 40 s later it comes back with a fresh boot. Finally The Breach is played until it ends. A simulated player shoots red targets after about 800 ± 250 ms and fires a stray shot at a dark node every 15–30 s.

The script fails if any of these happen:
- Duplicate or non-sequential IDs.
- A node dead for more than 16 s still counted as online, or still being sent commands.
- A dead node detected more or less than once.
- During Time Attack+, the player has nothing live to shoot for more than 2.5 s.

## Results (2026-10-23, branch `review/full-pass`)

| Nodes | Seed | IDs assigned | Hits per node (Time Attack+, 2 min) | Longest wait with no live target | Dead node detected after | Result |
|------:|-----:|--------------|------------------------------------|------------------------:|-------------------------:|--------|
| 1 | 1 | 1 | 53 | 1.3 s | 2.3 s | OK |
| 2 | 3 | 1–2 | 48 / 24 (node 2 dead for 40 s) | 1.8 s | 1.6 s | OK |
| 4 | 4 | 1–4 | 26 26 16 26 (node 3 dead for 40 s) | 2.3 s | 2.2 s | OK |
| 8 | 1 | 1–8 | 10–13 each | 1.6 s | 11.4 s | OK |
| 10 | 5 | 1–10 | 8–10 each | 1.3 s | 12.0 s | OK |
| 12 | 7 | 1–12 | 7–9 each | 1.3 s | 15.6 s | OK |
| 16 | 11 | 1–16 | 5–7 each | 2.2 s | 13.8 s | OK |

How to read the detection column:
- **Fast (~2 s):** the dead node was a lit target, or became one. Its missing ACK on the LED command (re-sent every 2 s) drops it within about a second.
- **Slow (11–16 s):** the dead node wasn't involved in the game, so the 15 s heartbeat timeout caught it. That's harmless, because the game never waited on it.

### Bugs this testing found and fixed
- **Before the 2 s re-send:** with 4 nodes, the lit target died and the player had **13.3 s** with nothing to shoot, until the heartbeat timeout fired. Fixed by re-sending red to lit targets every 2 s. A missing ACK marks the node unreachable (`NodeRegistry.mark_unreachable`), and `check_nodes()` drops it within 1 s.
- **Breach bonus compounding** (REVIEW #13), caught by `tests/test_game_modes.py`.
- **Time Attack+ re-lighting the node that was just hit** (REVIEW #12). The no-repeat test and the 10-node fairness test cover it.

## Real hardware (1 hub + 1 node)

| Test | Result |
|------|--------|
| Node registers with no code change, from its STA MAC | ID 1 (its claimed ID), saved in `nodes.json` |
| Simulated hits from the node during Time Attack+ | 5 of 5 delivered by unicast, 0 failed sends |
| Node program stopped (radio still up) | Offline after the 15 s heartbeat timeout, rejoins right after reset |
| Node radio off (emulates power loss) while lit | Missed ACK → offline in about 2 s |
| `/stop` | Nodes go to Standby, then Idle 10 s later |
| Exception in a game tick or in packet handling | Game aborts cleanly, listener keeps running |
| HTTP/WebSocket from an on-device client | Handshake OK, initial state sent, bad `/start` → 400 with reason, closed client dropped |

## Limits not covered by simulation
- **ESP-NOW peer table:** about 20 peers, including the broadcast peer, so at most **19 nodes online at once**. The fake radio doesn't model this. The hub frees a peer when its node goes offline.
- **Real radio timing.** The simulation adds no airtime. On hardware, a `sync=True` unicast took about 4 ms with an ACK and 8 ms without one (measured on the ESP8266).
- **Hub memory with many phones:** see REVIEW #36.
