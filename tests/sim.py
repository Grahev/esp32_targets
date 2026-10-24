"""PC simulation of the hub for game-mode tests: fake clock, fake engine, N nodes.

The game modes are MicroPython code; on CPython we give them a fake `time`
module (ticks_*) and a seeded `random`, then drive tick() by hand.
"""
import os
import random as _random
import sys

HUB_DIR = os.path.join(os.path.dirname(__file__), '..', 'hub')
if HUB_DIR not in sys.path:
    sys.path.insert(0, HUB_DIR)

import mode_time_attack  # noqa: E402
import mode_breach  # noqa: E402


class FakeTime:
    def __init__(self):
        self.now = 100000

    def ticks_ms(self):
        return self.now

    def ticks_add(self, t, d):
        return t + d

    def ticks_diff(self, a, b):
        return a - b

    def sleep(self, s):
        raise AssertionError('game code must not block (time.sleep)')

    def sleep_ms(self, ms):
        raise AssertionError('game code must not block (time.sleep_ms)')


class FakeEngine:
    """Stands in for HUB_SYSTEM: records LED state per node and WS messages."""

    def __init__(self, node_ids):
        self.available_nodes = sorted(node_ids)
        self.led = {n: (0, 0, 0) for n in node_ids}
        self.ws = []
        self.game_over_calls = 0

    def send_node_cmd(self, node_id, r, g, b):
        assert node_id in self.available_nodes, f'command sent to offline node {node_id}'
        self.led[node_id] = (r, g, b)

    def broadcast_led(self, r, g, b):
        for n in self.available_nodes:
            self.led[n] = (r, g, b)

    def broadcast_ws(self, msg):
        self.ws.append(msg)

    def game_over(self, save=True):
        self.game_over_calls += 1

    def lit(self, color=(255, 0, 0)):
        return sorted(n for n in self.available_nodes if self.led[n] == color)

    def drop_node(self, game, node_id):
        """Simulate the hub's node_lost(): leave the pool, tell the game."""
        self.available_nodes.remove(node_id)
        game.on_node_lost(node_id)

    def add_node(self, node_id):
        self.available_nodes.append(node_id)
        self.available_nodes.sort()
        self.led[node_id] = (0, 0, 0)


class Sim:
    def __init__(self, node_ids, seed=1):
        self.clock = FakeTime()
        for m in (mode_time_attack, mode_breach):
            m.time = self.clock
            m.random = _random.Random(seed)
        self.engine = FakeEngine(node_ids)

    def run(self, game, ms, step=100):
        """Advance the clock in tick-sized steps, calling game.tick()."""
        end = self.clock.now + ms
        while self.clock.now < end:
            self.clock.now += step
            game.tick()

    def run_until(self, game, cond, max_ms=60000, step=100):
        end = self.clock.now + max_ms
        while not cond():
            if self.clock.now >= end:
                raise AssertionError('condition not reached in time')
            self.clock.now += step
            game.tick()
