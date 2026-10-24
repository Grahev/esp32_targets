"""On-hub web load test. Compile to .mpy (a .py test would itself use enough RAM
to skew the result), upload, run, then delete:

  mpy-cross -o build/web_load.mpy tools/web_load.py
  mpremote connect $HUB cp build/web_load.mpy :web_load.mpy + exec "import web_load" + rm :web_load.mpy

Starts the real hub (hub_app) and hits its web server from the hub itself:
WebSocket clients, concurrent page loads, API calls and a game start/stop,
printing the IDF heap (what WiFi allocates from) throughout. Client and
server both run on the hub, so every connection uses 2 of its 10 sockets:
keep (WS clients + concurrent requests) * 2 + 1 <= 10.
"""
import gc
import time
import esp32
import asyncio
import hub_app as main
from hub_app import hub


def idf():
    return sum(h[1] for h in esp32.idf_heap_info(esp32.HEAP_DATA))


def report(label):
    gc.collect()
    print('W> %-26s idf_free %6d  py_alloc %6d  ws_clients %d' % (label, idf(), gc.mem_alloc(), len(main.connected_clients)))


async def get(path, ws=False):
    r, w = await asyncio.open_connection('192.168.4.1', 80)
    req = 'GET %s HTTP/1.1\r\nHost: hub\r\n' % path
    if ws:
        req += 'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
    w.write((req + '\r\n').encode())
    await w.drain()
    return r, w


async def fetch(path):
    try:
        return await _fetch(path)
    except OSError as ex:
        return 'ERR %s' % ex


async def _fetch(path):
    r, w = await get(path)
    try:
        total = 0
        status = await r.readline()
        while True:
            chunk = await r.read(256)
            if not chunk:
                break
            total += len(chunk)
        return status.split(b' ')[1], total
    finally:
        await w.wait_closed()


async def ws_client(i, frames):
    r, w = await get('/ws', ws=True)
    head = await r.readline()
    while (await r.readline()) not in (b'\r\n', b''):
        pass
    try:
        while True:
            hdr = await asyncio.wait_for(r.readexactly(2), 30)
            n = hdr[1] & 0x7F
            if n == 126:
                n = int.from_bytes(await r.readexactly(2), 'big')
            await r.readexactly(n)
            frames[i] += 1
    except Exception:
        pass
    await w.wait_closed()
    return head


async def run():
    report('module loaded')
    main.setup_wifi()
    main.start_tasks()
    asyncio.create_task(main.app.start_server(port=80))
    await asyncio.sleep(2)
    report('server up')
    print('W> 3 concurrent pages, no WS:', await asyncio.gather(fetch('/'), fetch('/'), fetch('/')))
    frames = [0, 0]
    clients = [asyncio.create_task(ws_client(i, frames)) for i in range(2)]
    await asyncio.sleep(2)
    report('2 WebSocket clients')
    seq = []
    for _ in range(3):
        seq.append(await fetch('/'))
    print('W> 3 sequential pages, 2 WS:', seq)
    print('W> 2 concurrent pages, 2 WS:', await asyncio.gather(fetch('/'), fetch('/')))
    report('after page loads')
    print('W> leaderboard:', await fetch('/api/leaderboard?mode=TimeAttack'))
    print('W> start:', await fetch('/start?mode=TimeAttack&duration=1'))
    for _ in range(4):
        await asyncio.sleep(2)
        report('game running')
    print('W> stop:', await fetch('/stop'))
    await asyncio.sleep(1)
    report('after stop')
    # Same work as saving a finished game's score, on a temp copy (the real
    # scores files are only read)
    import os
    from storage import load_json, save_json
    rows = load_json('scores_TimeAttack.json', [])
    rows.append({"hits": 1, "score": 1, "max_combo": 1, "penalties": 0,
                 "difficulty": "Normal", "duration_min": 1.0, "avg_rt": 900.0})
    rows.sort(key=lambda x: x['score'], reverse=True)
    save_json('_loadtest.json', rows[:20])
    del rows
    for ws in main.connected_clients:
        asyncio.create_task(main.ws_call(ws, main.send_leaderboard(ws, 'TimeAttack')))
    os.remove('_loadtest.json')
    await asyncio.sleep(1)
    report('after score-save work')
    # Game modes are unloaded after each game: several cycles must keep working
    # without growing the heap
    for mode in ('TimeAttack', 'TheBreach') * 4:
        started = await fetch('/start?mode=%s' % mode)
        await asyncio.sleep(2)
        state = hub.game and hub.game.state
        stopped = await fetch('/stop')
        await asyncio.sleep(1)
        report('cycle %s %s/%s %s' % (mode, started[0].decode(), stopped[0].decode(), state))
    print('W> frames received per client:', frames)
    for c in clients:
        c.cancel()
    await asyncio.sleep(1)
    report('clients gone')


asyncio.run(run())
