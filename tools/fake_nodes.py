"""Simulate N nodes against the real hub code on the PC (virtual clock, no radio).

  python3 tools/fake_nodes.py [--nodes 8] [--seed 1]

The hub's real main.py, game_engine.py, node_registry.py and the v2 packet
format run unchanged (MicroPython-only modules are stubbed, see
tests/hub_env.py). Each fake node behaves like node/main.py: it announces
every 5 s, obeys SET_ID / SET_MODE / SET_LED, and a simulated player shoots
at red targets with a human reaction time and the occasional stray shot.

Scenario: nodes boot at staggered times -> Time Attack+ (2 min) during which
one node dies and later comes back -> The Breach until the player fails.
Prints a report and exits non-zero if an invariant is broken.
"""
import argparse
import asyncio
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))
from hub_env import main, fresh_hub  # noqa: E402
from common.espnow_utils import (pack_message, unpack_command, MSG_TYPE_ANNOUNCE, MSG_TYPE_HIT,  # noqa: E402
                                 CMD_SET_LED, CMD_SET_MODE, CMD_SET_ID, BROADCAST)

RED = (255, 0, 0)
BLUE = (0, 0, 255)


class FakeNode:
    def __init__(self, n, boot_at):
        self.mac = bytes([0x48, 0x55, 0x19, 0xA0, 0x00, n])
        self.node_id = 0  # no config.json: the hub assigns one
        self.boot_at = boot_at
        self.alive = True
        self.seq = 0
        self.mode = 0
        self.led = (0, 0, 0)
        self.next_announce = boot_at

    def packet(self, msg_type, hit=False):
        self.seq = (self.seq + 1) & 0xFFFF
        return pack_message(self.node_id, self.seq, 3.9, 80, msg_type, hit=hit)

    def receive(self, data):
        cmd = unpack_command(data)
        if not cmd:
            return
        cid, a, b, c = cmd
        if cid == CMD_SET_ID:
            self.node_id = a
        elif cid == CMD_SET_MODE:
            self.mode = a
            self.led = (0, 0, 0)
        elif cid == CMD_SET_LED and self.mode == 1:
            self.led = (a, b, c)


class World:
    def __init__(self, n_nodes, seed):
        self.rng = random.Random(seed)
        self.hub, self.clock = fresh_hub()
        self.hub.broadcast_ws = self.on_ws
        self.nodes = [FakeNode(i + 1, self.clock.now + i * 700) for i in range(n_nodes)]
        self.by_mac = {nd.mac: nd for nd in self.nodes}
        self.events = []
        self.errors = []
        self.radio_loss = 0.02  # 2% of node packets lost before the hub sees them
        self.lost_packets = 0
        self.player_target = None  # (node, shoot_at_ms)
        self.next_stray = None
        self.hits_on = Counter()
        self.detect_ms = []
        self.no_target_ms = 0      # current stretch of play with nothing live to shoot
        self.max_no_target_ms = 0
        real_send = self.hub.esp.send

        def send(mac, msg, sync=True):
            real_send(mac, msg, sync)
            nd = self.by_mac.get(mac)
            return mac == BROADCAST or (nd is not None and nd.alive)  # dead nodes don't ACK
        self.hub.esp.send = send

    def on_ws(self, msg):
        if msg.get('type') == 'status' and ('Joined' in msg['msg'] or 'Offline' in msg['msg']):
            self.events.append((self.clock.now, msg['msg']))
            if 'Offline' in msg['msg']:
                nid = int(msg['msg'].split()[1])
                nd = next(n for n in self.nodes if n.node_id == nid)
                if not nd.alive:
                    self.detect_ms.append(self.clock.now - nd.dead_since)

    def node_send(self, nd, data):
        if self.rng.random() < self.radio_loss:
            self.lost_packets += 1
            if data[1] == MSG_TYPE_HIT:
                # the real node retries unicast hits; model one retry
                if self.rng.random() < self.radio_loss:
                    return
            else:
                return
        self.hub.handle_packet(nd.mac, data)

    def deliver_commands(self):
        for mac, data, _sync in self.hub.esp.sent:
            if mac == BROADCAST:
                targets = [nd for nd in self.nodes if nd.alive and self.clock.now >= nd.boot_at]
            else:
                nd = self.by_mac.get(mac)
                if nd is None:
                    self.errors.append(f'command to unknown MAC {mac.hex()}')
                    continue
                if not nd.alive:
                    if self.clock.now - nd.dead_since > 16000:
                        self.errors.append(f'command to node {nd.node_id} dead for >16 s')
                    continue
                targets = [nd]
            for nd in targets:
                nd.receive(data)
        self.hub.esp.sent.clear()

    def player(self):
        """Shoot the first red target after a human reaction time; sometimes miss."""
        now = self.clock.now
        if self.player_target is None:
            red = [nd for nd in self.nodes if nd.alive and nd.led == RED]
            if red:
                nd = self.rng.choice(red)
                self.player_target = (nd, now + max(250, int(self.rng.gauss(800, 250))))
        elif now >= self.player_target[1]:
            nd = self.player_target[0]
            self.player_target = None
            if nd.alive and nd.led == RED:
                self.hits_on[nd.node_id] += 1
                self.node_send(nd, nd.packet(MSG_TYPE_HIT, hit=True))
        if self.next_stray is None or now >= self.next_stray:
            if self.next_stray is not None:
                dark = [nd for nd in self.nodes if nd.alive and nd.led != RED and nd.node_id]
                if dark and self.hub.game:
                    nd = self.rng.choice(dark)
                    self.node_send(nd, nd.packet(MSG_TYPE_HIT, hit=True))
            self.next_stray = now + self.rng.randint(15000, 30000)

    def step(self, ms):
        """Advance virtual time in 10 ms slices, like the hub's event loop."""
        for _ in range(ms // 10):
            self.clock.now += 10
            now = self.clock.now
            for nd in self.nodes:
                if nd.alive and now >= nd.boot_at and now >= nd.next_announce:
                    self.node_send(nd, nd.packet(MSG_TYPE_ANNOUNCE))
                    nd.next_announce = now + 5000
            self.deliver_commands()
            if now % 100 == 0 and self.hub.game:
                self.hub.game.tick()
                self.deliver_commands()
            if now % 1000 == 0:
                self.hub.check_nodes()
            self.player()
            self.deliver_commands()
            self.check_invariants()
            g = self.hub.game
            if g and g.name == "Time Attack+" and g.state == "PLAYING":
                live_red = any(nd.alive and nd.led == RED for nd in self.nodes)
                any_alive = any(nd.alive for nd in self.nodes)
                self.no_target_ms = 0 if live_red or not any_alive else self.no_target_ms + 10
                self.max_no_target_ms = max(self.max_no_target_ms, self.no_target_ms)

    def check_invariants(self):
        online = set(self.hub.available_nodes)
        for nd in self.nodes:
            if nd.node_id and nd.node_id in online and not nd.alive and \
                    self.clock.now - nd.dead_since > 16000:
                self.errors.append(f'node {nd.node_id} dead for >16 s but still online')
        ids = [nd.node_id for nd in self.nodes if nd.node_id]
        if len(ids) != len(set(ids)):
            self.errors.append(f'duplicate node IDs {ids}')


async def run(n_nodes, seed):
    w = World(n_nodes, seed)
    say = print
    w.step(n_nodes * 700 + 6000)
    ids = sorted(nd.node_id for nd in w.nodes)
    say(f'Boot: {n_nodes} nodes joined, IDs {ids}, online {w.hub.available_nodes}')
    if ids != list(range(1, n_nodes + 1)):
        w.errors.append(f'IDs not 1..{n_nodes}: {ids}')

    # --- Time Attack+ with a node dying and coming back ---
    reply = await main.start_game(Req({'mode': 'TimeAttack', 'duration': '2', 'difficulty': 'Hard'}))
    say(f'Time Attack+ start: {reply}')
    victim = w.nodes[n_nodes // 2]
    w.step(30000)
    victim.alive, victim.dead_since = False, w.clock.now
    victim.led = (0, 0, 0)
    say(f'  t=30 s: node {victim.node_id} loses power')
    w.step(40000)
    victim.alive, victim.next_announce = True, w.clock.now
    victim.mode, victim.seq = 0, 0  # it rebooted
    say(f'  t=70 s: node {victim.node_id} back')
    w.step(55000)
    ta_scores = w.hub.get_leaderboard('TimeAttack')
    say(f'Time Attack+ result: {ta_scores[0] if ta_scores else "no score saved"}')
    say(f'  hits per node: {dict(sorted(w.hits_on.items()))}')
    say(f'  longest wait with no live target: {w.max_no_target_ms / 1000:.1f}s')
    if w.max_no_target_ms > 2500:  # spawn delay 1.2 s + freeze 1 s + slack
        w.errors.append(f'player had nothing to shoot for {w.max_no_target_ms} ms')
    if not ta_scores:
        w.errors.append('Time Attack+ score not saved')

    # --- The Breach: player remembers the sequence perfectly, slows down ---
    w.hub.cancel_idle_timer()
    w.player_target, w.next_stray = None, 10 ** 12  # no stray shots in this mode
    say(f'The Breach start: {await main.start_game(Req({"mode": "TheBreach"}))}')
    level_seen = 0
    while w.hub.game and w.clock.now < w.clock.now + 600000:
        g = w.hub.game
        if g.state == 'PLAYING':
            delay = 900 + g.level * 350  # gets slower: eventually misses the 5 s window
            for nid in list(g.sequence[g.current_idx:]):
                w.step(delay)
                if w.hub.game is not g or g.state != 'PLAYING':
                    break
                nd = next(n for n in w.nodes if n.node_id == nid)
                w.node_send(nd, nd.packet(MSG_TYPE_HIT, hit=True))
                w.step(200)
            level_seen = max(level_seen, g.level)
        w.step(100)
    br = w.hub.get_leaderboard('TheBreach')
    say(f'The Breach result: reached level {level_seen}, saved {br[0] if br else "nothing"}')
    w.hub.cancel_idle_timer()

    say('Join/offline events: ' + ', '.join(f'{(t - 1000) / 1000:.0f}s {m}' for t, m in w.events))
    say(f'Radio: {w.lost_packets} node packets dropped by the simulated 2% loss')
    say(f'Dead node detected after: {[f"{ms / 1000:.1f}s" for ms in w.detect_ms]}')
    if len(w.detect_ms) != 1:
        w.errors.append('node death not detected exactly once')
    if w.errors:
        say('PROBLEMS:')
        for e in dict.fromkeys(w.errors):
            say('  - ' + e)
        return 1
    say('OK: no invariant broken')
    return 0


class Req:
    def __init__(self, args):
        self.args = args


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--nodes', type=int, default=8)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    import io
    import contextlib
    log = io.StringIO()
    with contextlib.redirect_stdout(log):  # hub prints go to the log, report goes out
        code = asyncio.run(run(a.nodes, a.seed))
    report = [l for l in log.getvalue().splitlines()
              if l.startswith(('Boot', 'Time Attack+ start', 'Time Attack+ result', '  ', 'The Breach start',
                               'The Breach result', 'Join', 'Radio', 'Dead', 'PROBLEMS', 'OK'))]
    print('\n'.join(report))
    sys.exit(code)
