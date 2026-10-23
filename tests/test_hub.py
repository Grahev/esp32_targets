import asyncio
import json
import struct
import unittest

from hub_env import main, fresh_hub
from common.espnow_utils import (pack_message, unpack_command, MSG_TYPE_HIT, MSG_TYPE_ANNOUNCE,
                                 CMD_SET_LED, CMD_SET_MODE, CMD_SET_ID, BROADCAST)


def mac(n):
    return bytes([0x48, 0x55, 0, 0, 0, n])


def announce(claimed=0, seq=1):
    return pack_message(claimed, seq, 3.9, 80, MSG_TYPE_ANNOUNCE)


def hit(claimed, seq):
    return pack_message(claimed, seq, 3.9, 80, MSG_TYPE_HIT, hit=True)


def cmds_to(hub, m):
    return [unpack_command(b) for (dst, b, _) in hub.esp.sent if dst == m]


class Recorder:
    def __init__(self, hub):
        self.ws = []
        hub.broadcast_ws = self.ws.append


class TestRegistration(unittest.TestCase):
    def setUp(self):
        self.hub, self.clock = fresh_hub()
        self.rec = Recorder(self.hub)

    def test_ten_new_nodes_get_unique_ids_without_config(self):
        for n in range(1, 11):
            self.hub.handle_packet(mac(n), announce(claimed=0))
        self.assertEqual(self.hub.available_nodes, list(range(1, 11)))
        # every node was told its ID and the current mode
        for n in range(1, 11):
            got = cmds_to(self.hub, mac(n))
            self.assertIn((CMD_SET_ID, n, 0, 0), got)
            self.assertIn((CMD_SET_MODE, 0, 0, 0), got)

    def test_claimed_id_kept_when_free_and_ids_survive_reboot(self):
        self.hub.handle_packet(mac(1), announce(claimed=5))
        self.hub.handle_packet(mac(2), announce(claimed=5))  # duplicate claim
        self.assertEqual(self.hub.available_nodes, [1, 5])
        with open('nodes.json') as f:
            saved = json.load(f)
        self.assertEqual(sorted(saved.values()), [1, 5])
        rebooted = main.HUB_SYSTEM()
        self.assertEqual(rebooted.registry.node_id_for(mac(2), 9), 1)

    def test_v1_packets_still_accepted(self):
        v1 = struct.pack('ifiBiB', 3, 4.0, 90, 0, MSG_TYPE_ANNOUNCE, 0)
        self.hub.handle_packet(mac(9), v1)
        self.assertEqual(self.hub.available_nodes, [3])

    def test_unknown_packet_is_ignored(self):
        self.hub.handle_packet(mac(1), b'garbage')
        self.assertEqual(self.hub.available_nodes, [])


class TestHitsAndDuplicates(unittest.TestCase):
    def setUp(self):
        self.hub, self.clock = fresh_hub()
        Recorder(self.hub)
        self.hits = []
        self.hub.game = type('G', (), {'on_hit': lambda s, n: self.hits.append(n),
                                       'on_node_lost': lambda s, n: None})()

    def test_retried_hit_counts_once(self):
        self.hub.handle_packet(mac(1), hit(0, seq=7))
        self.clock.now += 5
        self.hub.handle_packet(mac(1), hit(0, seq=7))  # radio retry
        self.clock.now += 400
        self.hub.handle_packet(mac(1), hit(0, seq=8))
        self.assertEqual(self.hits, [1, 1])

    def test_simultaneous_hits_from_many_nodes(self):
        for n in range(1, 9):
            self.hub.handle_packet(mac(n), announce())
        for n in range(1, 9):
            self.hub.handle_packet(mac(n), hit(n, seq=2))
        self.assertEqual(sorted(self.hits), list(range(1, 9)))


class TestOffline(unittest.TestCase):
    def setUp(self):
        self.hub, self.clock = fresh_hub()
        self.rec = Recorder(self.hub)
        self.lost = []
        self.hub.game = type('G', (), {'on_hit': lambda s, n: None,
                                       'on_node_lost': lambda s, n: self.lost.append(n)})()
        for n in (1, 2, 3):
            self.hub.handle_packet(mac(n), announce(claimed=n))

    def test_silent_node_goes_offline_and_comes_back(self):
        for _ in range(4):  # nodes 1 and 3 keep sending heartbeats
            self.clock.now += 5000
            for n in (1, 3):
                self.hub.handle_packet(mac(n), announce(claimed=n, seq=self.clock.now))
            self.hub.check_nodes()
        self.assertEqual(self.hub.available_nodes, [1, 3])
        self.assertEqual(self.lost, [2])
        self.assertNotIn(mac(2), self.hub.esp.peers)
        self.assertIn({"type": "nodes", "online": [1, 3]}, self.rec.ws)

        self.hub.handle_packet(mac(2), announce(claimed=2, seq=99))
        self.assertEqual(self.hub.available_nodes, [1, 2, 3])
        self.assertIn(mac(2), self.hub.esp.peers)

    def test_commands_only_go_to_online_nodes(self):
        self.clock.now += 16000
        self.hub.handle_packet(mac(1), announce(claimed=1, seq=50))
        self.hub.check_nodes()
        self.hub.esp.sent.clear()
        self.hub.broadcast_led(255, 0, 0)
        self.assertEqual([d for d, _, _ in self.hub.esp.sent], [mac(1)])
        self.hub.esp.sent.clear()
        self.hub.send_node_cmd(2, 255, 0, 0)
        self.assertEqual(self.hub.esp.sent, [])

    def test_set_mode_also_broadcast_for_unregistered_nodes(self):
        self.hub.esp.sent.clear()
        self.hub.set_system_mode(2)
        dests = [d for d, _, _ in self.hub.esp.sent]
        self.assertIn(BROADCAST, dests)
        self.assertEqual(len(dests), 4)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.hub, self.clock = fresh_hub()
        self.rec = Recorder(self.hub)
        self.hub.handle_packet(mac(1), announce(claimed=1))

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_stop_puts_nodes_in_standby_without_saving(self):
        async def go():
            await main.start_game(Req({'mode': 'TimeAttack', 'duration': '1'}))
            self.assertEqual(self.hub.sys_mode, 1)
            await main.stop_game(Req({}))
            self.assertIsNone(self.hub.game)
            self.assertEqual(self.hub.sys_mode, 2)
            self.hub.cancel_idle_timer()
        self.run_async(go())
        self.assertEqual(self.hub.get_leaderboard('TimeAttack'), [])

    def test_start_rejects_bad_requests_with_reason(self):
        async def go():
            bad = [{'mode': 'Zombie'},
                   {'mode': 'TimeAttack', 'duration': 'abc'},
                   {'mode': 'TimeAttack', 'duration': '0'},
                   {'mode': 'TimeAttack', 'difficulty': 'Insane'}]
            for args in bad:
                reply = await main.start_game(Req(args))
                self.assertEqual(reply[1], 400, args)
            self.assertIsNone(self.hub.game)
        self.run_async(go())

    def test_start_without_nodes_is_refused(self):
        hub, _ = fresh_hub()
        Recorder(hub)
        reply = asyncio.run(main.start_game(Req({'mode': 'TheBreach'})))
        self.assertEqual(reply[1], 409)

    def test_start_while_running_replaces_game_cleanly(self):
        async def go():
            await main.start_game(Req({'mode': 'TimeAttack'}))
            first = self.hub.game
            self.assertEqual(await main.start_game(Req({'mode': 'TheBreach'})), "OK")
            self.assertEqual(first.state, "FINISHED")
            self.assertEqual(self.hub.game.name, "The Breach")
            self.assertEqual(self.hub.sys_mode, 1)
            self.hub.cancel_idle_timer()
        self.run_async(go())


class Req:
    def __init__(self, args):
        self.args = args


class SlowWS:
    """A client whose socket never drains (phone went to sleep)."""

    class writer:
        @staticmethod
        async def aclose():
            pass

    async def send(self, data):
        await asyncio.sleep(3600)


class FastWS(SlowWS):
    def __init__(self):
        self.got = []

    async def send(self, data):
        self.got.append(data)


class TestWebSocketClients(unittest.TestCase):
    def test_stuck_client_is_dropped_others_keep_receiving(self):
        hub, _ = fresh_hub()
        main.WS_SEND_TIMEOUT = 0.05
        slow, fast = SlowWS(), FastWS()
        main.connected_clients.extend([slow, fast])

        async def go():
            hub.broadcast_ws({"type": "status", "msg": "x"})
            await asyncio.sleep(0.2)
            hub.broadcast_ws({"type": "status", "msg": "y"})
            await asyncio.sleep(0.05)
        asyncio.run(go())
        self.assertEqual(main.connected_clients, [fast])
        self.assertEqual(len(fast.got), 2)


if __name__ == '__main__':
    unittest.main()
