# Review progress — branch `review/full-pass`

Resume from the first unchecked item. Board backups: `./backup_hub/`, `./backup_node/` (taken 2026-10-23, before any change).

## Setup
- [x] Branch `review/full-pass` created from `master`
- [x] `.gitignore` created (it did not exist): backup folders, `__pycache__`
- [x] Both boards backed up
- [x] Both boards respond to `mpremote ls`
- [x] This file

## Phase 1 — Understand the project
- [x] Read all repo files and board files; list differences
- [x] CLAUDE.md "How the project works" (complete)
- [x] ARCHITECTURE.md

## Phase 2 — Code review
- [x] REVIEW.md with Critical / High / Medium / Low findings (1 Critical, 5 High, 12 Medium, 17 Low)

## Phase 3 — Fix (Critical → Medium)
- [x] #1 atomic score save + corrupt-file guard
- [x] #2 /stop returns nodes to standby/idle
- [x] #3 guarded listener/game loop, crash -> reset
- [x] #4 + #18 node heartbeat/offline tracking, peer cleanup
- [x] #5 + #7 + #6 protocol v2: unicast hits w/ retry, seq dedupe, MAC-based IDs (hub+node)
- [x] #8 #9 #10 node: AP off, throttled ADC/LED, guarded loop
- [x] #11 remove blocking sleeps
- [x] #12 Time Attack+ spawn delay / no-repeat
- [x] #13 Breach bonus compounding
- [x] #14 websocket send timeout / drop dead clients
- [x] #15 start/stop validation + UI feedback
- [x] #16 test suite
- [ ] #17 top-level crash recovery (WDT -> needs discussion)

## Phase 4 — Multi-node readiness
- [x] Node identity from MAC, no code edits to add a node (done with #6)
- [x] Hub tracks join / heartbeat / offline (done with #4)
- [ ] tools/fake_nodes.py written and run, results recorded
- [ ] docs/ADDING_A_NODE.md

## Phase 5 — Features
- [ ] FEATURES.md

## Finish
- [ ] Summary at top of REVIEW.md, all committed on branch

## Notes
- Every `mpremote` command stops `main.py`; reset boards afterwards (node first, then hub).
- `mpremote repl` needs a TTY here; read boot logs with pyserial (see tools/serial_log.py once written).
- Board vs repo (Phase 1): code identical apart from CRLF endings; board-only = boot.py (default) + scores_*.json; repo-only = docs/, tests/, prd.md, README.md.
- Existing tests are stale: test_time_attack.py imports a removed class, test_protocol.py uses an old pack_message signature.
- Left on hub by a test: `_selftest.json` (13 bytes). Needs user OK to delete.
- Hub memory (#36): idf_free ~37 KB after boot. Test files left on hub by the investigation: `/microdot*.mpy` (3 files, same code as lib/, currently loaded first because `/` precedes `/lib` in sys.path) and `/app/` (compiled test copies). Need user OK to delete.
- Harness scripts must stay small (big scripts grow the heap and starve WiFi): use a trimmed copy with only the needed scenario.
