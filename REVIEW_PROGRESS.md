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
- [ ] REVIEW.md with Critical / High / Medium / Low findings

## Phase 3 — Fix (Critical → Medium)
- [ ] (fix list filled in after Phase 2)

## Phase 4 — Multi-node readiness
- [ ] Node identity from MAC, no code edits to add a node
- [ ] Hub tracks join / heartbeat / offline
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
