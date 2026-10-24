"""Convert a v1 hub backup (MicroPython) into a v2 backup file.

Usage: python3 tools/migrate_v1.py BACKUP_DIR [OUT.json]
  BACKUP_DIR  folder made with `mpremote cp -r : BACKUP_DIR/` from a v1 hub
  OUT.json    default: BACKUP_DIR/v2-migration.json

Then on the phone: Settings > Data > Restore backup, and pick OUT.json.

What is converted:
  nodes.json              -> targets (same MAC keeps the same number)
  scores_TimeAttack.json  -> Time Attack+ leaderboard
  scores_TheBreach.json   -> The Breach leaderboard (0-point games dropped, v1 #24)
Not converted: scores_time_attack.json (old format; dropped as agreed on
2026-10-24) and settings (so restoring never changes the hub's system ID).
v1 saved no player names or dates: rows are shown as player "v1".
"""
import json
import os
import sys

TOP_N = 50


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def time_attack(rows):
    out = []
    for r in rows:
        dur = r.get('duration_min', 1) or 1
        diff = r.get('difficulty', 'Normal')
        out.append({
            's': int(r.get('score', 0)), 'p': 0, 'n': 'v1', 'd': 0,
            'l': f"{diff} · {int(round(dur))} min",
            'hits': int(r.get('hits', 0)), 'misses': int(r.get('penalties', 0)),
            'avg_rt': int(round(r.get('avg_rt', 0) or 0)), 'max_combo': int(r.get('max_combo', 0)),
            'difficulty': diff, 'duration_min': int(round(dur)),
        })
    return out


def breach(rows):
    out = []
    for r in rows:
        if not r.get('score'):
            continue
        out.append({'s': int(r['score']), 'p': 0, 'n': 'v1', 'd': 0, 'l': 'Standard',
                    'level': int(r.get('level', 1)), 'hits': int(r.get('hits', 0))})
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(src, 'v2-migration.json')

    nodes = []
    for mac, slot in sorted(load(os.path.join(src, 'nodes.json'), {}).items(), key=lambda kv: kv[1]):
        nodes.append({'mac': mac.lower(), 'slot': int(slot), 'name': f'Target {slot}', 'color': int(slot) % 8, 'cfg': {}})

    scores = {
        'time_attack': time_attack(load(os.path.join(src, 'scores_TimeAttack.json'), [])),
        'breach': breach(load(os.path.join(src, 'scores_TheBreach.json'), [])),
    }
    for k in scores:
        scores[k] = sorted(scores[k], key=lambda e: -e['s'])[:TOP_N]

    backup = {'format': 'targets-backup', 'version': 2, 'fw': 'migrated-from-v1',
              'nodes': nodes, 'scores': scores, 'history': []}
    with open(dst, 'w') as f:
        json.dump(backup, f, ensure_ascii=False)
    print(f"{dst}: {len(nodes)} target(s), "
          + ", ".join(f"{k} {len(v)} score(s)" for k, v in scores.items()))


if __name__ == '__main__':
    main()
