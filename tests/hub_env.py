"""Import the real hub program (hub/hub_app.py) on CPython, with MicroPython-only modules stubbed.

Gives tests a fake radio (FakeESP) and a fake clock shared by main.py,
node_registry.py and the game mode modules.
"""
import asyncio
import json
import os
import sys
import tempfile
import traceback
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (ROOT, os.path.join(ROOT, 'hub')):
    if p not in sys.path:
        sys.path.insert(0, p)

sys.print_exception = lambda e: traceback.print_exception(type(e), e, e.__traceback__)


class FakeWLAN:
    def __init__(self, *a):
        pass

    def active(self, *a):
        return True

    def config(self, *a, **k):
        return 1

    def ifconfig(self, *a):
        pass


def _install_stubs():
    sys.modules['uasyncio'] = asyncio
    sys.modules['ujson'] = json
    net = types.ModuleType('network')
    net.STA_IF, net.AP_IF, net.AUTH_OPEN = 0, 1, 0
    net.WLAN = FakeWLAN
    sys.modules['network'] = net
    sys.modules['espnow'] = types.ModuleType('espnow')
    machine = types.ModuleType('machine')
    machine.reset = lambda: None
    sys.modules['machine'] = machine


class FakeClock:
    def __init__(self):
        self.now = 1000

    def ticks_ms(self):
        return self.now

    def ticks_add(self, t, d):
        return t + d

    def ticks_diff(self, a, b):
        return a - b


class FakeESP:
    def __init__(self):
        self.sent = []  # (mac, bytes, sync)
        self.peers = set()
        self.ack = True

    def add_peer(self, mac):
        if mac in self.peers:
            raise OSError('ESP_ERR_ESPNOW_EXIST')
        self.peers.add(mac)

    def del_peer(self, mac):
        self.peers.discard(mac)

    def send(self, mac, msg, sync=True):
        self.sent.append((mac, bytes(msg), sync))
        return self.ack


_install_stubs()
os.chdir(tempfile.mkdtemp())  # nodes.json / scores files land here
import hub_app as main  # noqa: E402
import mode_time_attack  # noqa: E402
import mode_breach  # noqa: E402
import node_registry  # noqa: E402


def fresh_hub():
    """New HUB_SYSTEM with fake radio and clock, installed as main.hub."""
    for f in os.listdir('.'):
        os.remove(f)
    clock = FakeClock()
    main.time = clock
    mode_time_attack.time = clock
    mode_breach.time = clock
    node_registry.ticks_diff = clock.ticks_diff
    hub = main.HUB_SYSTEM()
    hub.esp = FakeESP()
    main.hub = hub
    main.connected_clients.clear()
    return hub, clock
