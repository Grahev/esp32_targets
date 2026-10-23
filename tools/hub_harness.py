"""Hardware test harness that runs ON THE HUB:  timeout 90 mpremote connect $HUB run tools/hub_harness.py

Imports the real main.py (without starting the web server), runs the radio
listener and game loop, waits for nodes, then calls the HTTP route handlers
directly. Watch the node side at the same time with tools/serial_log.py.
Change SCENARIO to pick a test. Reset the hub afterwards.
"""
import time
import uasyncio as asyncio

import main
from main import hub

SCENARIO = 'stop'


class Req:
    def __init__(self, args):
        self.args = args


async def wait_nodes(n=1, ms=15000):
    t0 = time.ticks_ms()
    while len(hub.available_nodes) < n and time.ticks_diff(time.ticks_ms(), t0) < ms:
        await asyncio.sleep_ms(100)
    print('H> nodes', hub.available_nodes)


async def scenario_stop():
    # REVIEW #2: /stop must put nodes into Standby, then Idle
    print('H> start ->', await main.start_game(Req({'mode': 'TimeAttack', 'duration': '1'})))
    await asyncio.sleep(4)
    print('H> during game: sys_mode', hub.sys_mode, 'state', hub.game and hub.game.state)
    print('H> stop ->', await main.stop_game(Req({})))
    print('H> after stop: sys_mode', hub.sys_mode, 'game', hub.game)
    await asyncio.sleep(11)
    print('H> after 11 s: sys_mode', hub.sys_mode)


async def scenario_hits():
    # Play Time Attack for a while; tap the node to send real hits
    print('H> start ->', await main.start_game(Req({'mode': 'TimeAttack', 'duration': '1'})))
    await asyncio.sleep(30)
    print('H> stop ->', await main.stop_game(Req({})))


async def scenario_crash():
    # REVIEW #3: an exception in tick() aborts the game; one in packet
    # handling is logged and the listener keeps going
    print('H> start ->', await main.start_game(Req({'mode': 'TimeAttack', 'duration': '1'})))
    await asyncio.sleep(1)

    def bad_tick():
        raise ValueError('injected tick failure')
    hub.game.tick = bad_tick
    await asyncio.sleep_ms(500)
    print('H> after tick crash: game', hub.game, 'sys_mode', hub.sys_mode)

    real = hub.handle_packet
    seen = []

    def flaky(host, msg):
        seen.append(1)
        if len(seen) == 1:
            raise ValueError('injected packet failure')
        real(host, msg)
    hub.handle_packet = flaky
    await asyncio.sleep(12)
    print('H> packets after injected failure:', len(seen), '(>1 means listener survived)')


async def scenario_idle():
    # Just run the listener: shows registration, heartbeats, offline detection
    await asyncio.sleep(40)
    print('H> nodes', hub.available_nodes)


async def run():
    main.setup_wifi()
    asyncio.create_task(main.espnow_listener())
    asyncio.create_task(main.game_loop())
    await wait_nodes()
    await globals()['scenario_' + SCENARIO]()
    print('H> done')


asyncio.run(run())
