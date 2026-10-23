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


async def scenario_breach():
    # The Breach with real node hits (tools/node_fake_hit.py on the node)
    print('H> start ->', await main.start_game(Req({'mode': 'TheBreach'})))
    for _ in range(12):
        await asyncio.sleep(2)
        g = hub.game
        print('H> state', g and g.state, 'level', g and g.level, 'score', g and g.score)
    print('H> stop ->', await main.stop_game(Req({})))


async def http(path, ws=False):
    """Request our own web server over the AP's IP; return the raw reply."""
    r, w = await asyncio.open_connection('192.168.4.1', 80)
    hdr = 'GET %s HTTP/1.1\r\nHost: x\r\n' % path
    if ws:
        hdr += ('Connection: Upgrade\r\nUpgrade: websocket\r\n'
                'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n')
    w.write((hdr + '\r\n').encode())
    await w.drain()
    data = b''
    try:
        while len(data) < 3000:
            chunk = await asyncio.wait_for(r.read(512), 2)
            if not chunk:
                break
            data += chunk
    except asyncio.TimeoutError:
        pass
    return r, w, data


async def scenario_web():
    # Real HTTP server + a WebSocket client on the hub itself
    asyncio.create_task(main.app.start_server(port=80))
    await asyncio.sleep(1)
    r, w, data = await http('/ws', ws=True)
    print('H> ws handshake:', data.split(b'\r\n')[0])
    print('H> ws initial frames contain nodes msg:', b'"nodes"' in data, 'leaderboard:', b'leaderboard' in data)
    for path in ('/start?mode=TimeAttack&duration=abc', '/start?mode=Nope', '/stop'):
        _, w2, reply = await http(path)
        print('H> GET', path, '->', reply.split(b'\r\n')[0], reply.split(b'\r\n\r\n')[-1][:60])
        w2.close()
    print('H> clients before close', len(main.connected_clients))
    w.close()
    await asyncio.sleep(1)
    print('H> clients after close', len(main.connected_clients))


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
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < 50000:
        await asyncio.sleep(5)
        print('H> t=%ds online %s' % (time.ticks_diff(time.ticks_ms(), t0) // 1000, hub.available_nodes))


async def run():
    import network
    ap = network.WLAN(network.AP_IF)
    # main.py already set up the AP at boot; reconfiguring a running AP can
    # fail with "WiFi Out of Memory", so only do it if needed
    if not (ap.active() and ap.config('essid') == main.AP_SSID):
        main.setup_wifi()
    main.start_tasks()
    await wait_nodes()
    await globals()['scenario_' + SCENARIO]()
    print('H> done')


asyncio.run(run())
