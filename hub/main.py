import gc
import sys
import time
import machine
import network
import uasyncio as asyncio
import ujson as json

# Libraries
from common.espnow_utils import (init_espnow, unpack_message, pack_command, MSG_TYPE_HIT,
                                 CMD_SET_LED, CMD_SET_MODE, CMD_SET_ID, BROADCAST, WIFI_CHANNEL)
from microdot_asyncio import Microdot, Response, send_file
from microdot_websocket import with_websocket
from game_engine import TimeAttackPlus, TheBreach, DifficultyConfig
from storage import load_json, save_json
from node_registry import NodeRegistry, mac_key


# --- Configuration ---
AP_SSID = "Airsoft-Master"

# --- Globals ---
app = Microdot()
connected_clients = []
WS_SEND_TIMEOUT = 2  # s; a phone that went to sleep never ACKs, so don't wait forever


def drop_client(ws, close=True):
    if ws in connected_clients:
        connected_clients.remove(ws)
        print(f"WS client dropped ({len(connected_clients)} left)")
        if close:
            asyncio.create_task(close_client(ws))


async def close_client(ws):
    try:
        await ws.writer.aclose()  # also ends that client's receive loop
    except Exception:
        pass


async def ws_send(ws, msg_json):
    try:
        await asyncio.wait_for(ws.send(msg_json), WS_SEND_TIMEOUT)
    except Exception:
        drop_client(ws)

# --- System Class ---
class HUB_SYSTEM:
    def __init__(self):
        self.registry = NodeRegistry()
        self.node_macs = self.registry.macs  # Map ID -> MAC
        self.esp = None
        self.game = None
        self.wlan = None
        self.available_nodes = []  # online node IDs, sorted; read by the game modes
        self.node_battery = {}  # Map ID -> {'voltage', 'percent', 'charging'}
        self.sys_mode = 0 # 0=Idle, 1=Active, 2=Standby
        self._idle_task = None

    def set_system_mode(self, mode):
        # 0=Idle, 1=Active, 2=Standby
        print(f"Setting System Mode: {mode}")
        self.sys_mode = mode
        # Broadcast as well, so nodes the hub hasn't registered yet follow too
        self.broadcast_command(CMD_SET_MODE, mode, 0, 0, also_broadcast=True)

    async def _auto_idle(self):
        print("Standby... Waiting 10s for Idle")
        await asyncio.sleep(10)
        self.set_system_mode(0) # Switch to Idle
        print("Auto Idle Triggered")

    def cancel_idle_timer(self):
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None 

    def broadcast_ws(self, msg_dict):
        msg_json = json.dumps(msg_dict)
        for ws in connected_clients:
            asyncio.create_task(ws_send(ws, msg_json))
    
    def update_battery(self, node_id, voltage, percent=0, charging=False):
        self.node_battery[node_id] = {'voltage': voltage, 'percent': percent, 'charging': charging}
        # Broadcast battery update
        # We limit precision to 2 decimals to save bandwidth/noise
        self.broadcast_ws({
            "type": "battery", 
            "node_id": node_id, 
            "voltage": round(voltage, 2),
            "percent": percent,
            "charging": charging
        })

    def broadcast_nodes(self):
        self.broadcast_ws({"type": "nodes", "online": self.available_nodes})

    def handle_packet(self, host, msg):
        data = unpack_message(msg)
        if not data:
            print(f"Ignored {len(msg)}-byte packet from {host}")
            return
        ver, msg_type, claimed_id, seq, batt, pct, hit, charging = data
        now = time.ticks_ms()
        if self.registry.is_duplicate(host, seq, now):
            return  # node retried a packet we already handled
        node_id = self.registry.node_id_for(host, claimed_id)
        self.node_seen(node_id, host, now)
        if ver >= 2 and claimed_id != node_id:
            self.send_cmd(node_id, CMD_SET_ID, node_id, 0, 0)  # node stores it
        self.update_battery(node_id, batt, pct, charging)
        if msg_type == MSG_TYPE_HIT and hit:
            self.on_hit(node_id)

    def node_seen(self, node_id, mac, now):
        if not self.registry.seen(node_id, mac, now):
            return
        # Node just came online (first time, or back after a timeout)
        try:
            self.esp.add_peer(mac)
        except OSError as ex:
            # ESP-NOW holds ~20 peers; offline nodes are removed in node_lost()
            if 'EXIST' not in str(ex):
                print(f"add_peer failed for node {node_id}: {ex}")
        self.available_nodes.append(node_id)
        self.available_nodes.sort()
        print(f"Node {node_id} online ({mac_key(mac)}). Online: {self.available_nodes}")
        self.broadcast_ws({"type": "status", "msg": f"Node {node_id} Joined"})
        self.broadcast_nodes()
        # Sync the new node to the current mode
        self.send_cmd(node_id, CMD_SET_MODE, self.sys_mode, 0, 0)

    def check_nodes(self):
        """Drop nodes whose heartbeat stopped (called every second)."""
        for node_id in self.registry.expire(time.ticks_ms()):
            self.node_lost(node_id)

    def node_lost(self, node_id):
        if node_id in self.available_nodes:
            self.available_nodes.remove(node_id)
        print(f"Node {node_id} offline. Online: {self.available_nodes}")
        mac = self.node_macs.get(node_id)
        if mac:
            try:
                self.esp.del_peer(mac)
            except OSError:
                pass
        self.broadcast_ws({"type": "status", "msg": f"Node {node_id} Offline"})
        self.broadcast_nodes()
        if self.game:
            self.game.on_node_lost(node_id)

    def on_hit(self, node_id):
        print(f"HIT: Node {node_id}")
        if self.game:
            self.game.on_hit(node_id)
        self.broadcast_ws({"type": "hit", "node_id": node_id, "time": time.ticks_ms()})

    def send_cmd(self, node_id, cmd_id, a, b, c, sync=True):
        """Unicast a command to an online node. Unicast frames are ACKed and retried by the radio."""
        if not (self.esp and self.registry.is_online(node_id)):
            print(f"Cannot send to Node {node_id} (offline)")
            return False
        try:
            ok = self.esp.send(self.node_macs[node_id], pack_command(cmd_id, a, b, c), sync)
            if sync and not ok:
                print(f"Node {node_id} did not ACK cmd {cmd_id}")
            return ok
        except OSError as ex:
            print(f"Send Error to {node_id}: {ex}")
            return False

    def send_node_cmd(self, node_id, r, g, b):
        self.send_cmd(node_id, CMD_SET_LED, r, g, b)

    def broadcast_command(self, cmd_id, a, b, c, also_broadcast=False):
        if not self.esp:
            return
        # Unicast to every online node without waiting for each ACK
        # (the radio still retries), so 10 nodes don't stall the event loop
        for nid in self.available_nodes:
            self.send_cmd(nid, cmd_id, a, b, c, sync=False)
        if also_broadcast:
            try:
                self.esp.add_peer(BROADCAST)
            except OSError:
                pass
            try:
                self.esp.send(BROADCAST, pack_command(cmd_id, a, b, c), False)
            except OSError as ex:
                print(f"Broadcast Error: {ex}")

    def broadcast_led(self, r, g, b):
        self.broadcast_command(CMD_SET_LED, r, g, b)

    def game_over(self, save=True):
        # Called by a game mode when it ends (save=True) or by /stop (save=False)
        print("GAME OVER")
        if self.game:
            mode_name = "TimeAttack" if self.game.name == "Time Attack+" else "TheBreach"
            if save:
                self.save_score(self.game, mode_name)
            self.game = None

            self.broadcast_ws({"type": "status", "msg": "GAME OVER"})
            # Send updated leaderboard for that mode
            self.broadcast_ws({"type": "leaderboard", "mode": mode_name, "data": self.get_leaderboard(mode_name)})

            # Switch to Standby, then schedule Idle
            self.set_system_mode(2)
            self.cancel_idle_timer()
            self._idle_task = asyncio.create_task(self._auto_idle())

    def save_score(self, game_obj, mode):
        try:
            scores = self.get_leaderboard(mode)
            filename = f'scores_{mode}.json'
            
            new_score = {}
            if mode == "TimeAttack":
                duration_min = game_obj.duration_ms / 60000.0
                new_score = {
                    "hits": game_obj.hits,
                    "score": game_obj.score,
                    "max_combo": game_obj.max_combo,
                    "penalties": game_obj.penalty_count,
                    "difficulty": game_obj.difficulty,
                    "duration_min": duration_min,
                    "avg_rt": (sum(game_obj.reaction_times)/len(game_obj.reaction_times)) if game_obj.reaction_times else 0
                }
            elif mode == "TheBreach":
                new_score = {
                    "level": game_obj.level,
                    "score": game_obj.score,
                    "hits": 0, # Could track total hits if needed, but Level/Score is key
                    "avg_rt": 0 # Not tracked yet globally for breach?
                }

            scores.append(new_score)
            scores.sort(key=lambda x: x['score'], reverse=True)
            scores = scores[:20]
            
            save_json(filename, scores)
            print(f"Score Saved to {filename}")
        except Exception as e:
            print(f"Save Error: {e}")

    def get_leaderboard(self, mode="TimeAttack"):
        return load_json(f'scores_{mode}.json', [])

hub = HUB_SYSTEM()

# --- Web Server Routes ---
@app.route('/')
async def index(request):
    return send_file('hub/static/index.html')

@app.route('/api/leaderboard')
async def get_leaderboard_route(request):
    mode = request.args.get('mode', 'TimeAttack')
    return json.dumps(hub.get_leaderboard(mode))

@app.route('/ws')
async def websocket_handler(request):
    # Manual WebSocket upgrade to avoid decorator issues with async
    from microdot_websocket import WebSocket
    ws = WebSocket(request)
    await ws.handshake()
    print("WS Connected")
    connected_clients.append(ws)
    try:
        # Initial state: both leaderboards, online nodes, battery levels
        await ws.send(json.dumps({"type": "leaderboard", "mode": "TimeAttack", "data": hub.get_leaderboard("TimeAttack")}))
        await ws.send(json.dumps({"type": "leaderboard", "mode": "TheBreach", "data": hub.get_leaderboard("TheBreach")}))
        await ws.send(json.dumps({"type": "nodes", "online": hub.available_nodes}))
        for nid, data in hub.node_battery.items():
            await ws.send(json.dumps({
                "type": "battery",
                "node_id": nid,
                "voltage": round(data['voltage'], 2),
                "percent": data.get('percent', 0),
                "charging": data.get('charging', False)
            }))

        while True:
            msg = await ws.receive()
    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        drop_client(ws, close=False)  # microdot closes the socket after we return


@app.route('/start')
async def start_game(request):
    mode = request.args.get('mode', 'TimeAttack')
    print(f"Starting {mode}")
    if mode not in ('TimeAttack', 'TheBreach'):
        return f"Unknown mode {mode}", 400
    if not hub.available_nodes:
        return "No nodes online", 409

    if mode == 'TimeAttack':
        try:
            duration = int(request.args.get('duration', 1))
            delay = float(request.args.get('delay', 1.0))
        except ValueError:
            return "Bad duration or delay", 400
        diff = request.args.get('difficulty', 'Normal')
        if not 1 <= duration <= 30 or not 0.1 <= delay <= 10:
            return "Duration must be 1-30 min, delay 0.1-10 s", 400
        if diff not in DifficultyConfig.PENALTIES:
            return f"Unknown difficulty {diff}", 400
        pen = (request.args.get('penalties', 'true') == 'true')
        game = TimeAttackPlus(hub, duration_min=duration, difficulty=diff, penalties=pen, respawn_delay=delay)
    else:
        game = TheBreach(hub, start_level=1)

    if hub.game:
        # A new start replaces the running game: end that one cleanly first
        hub.game.stop()
        hub.game_over(save=False)
    hub.game = game
    hub.cancel_idle_timer() # Cancel pending idle if any
    hub.set_system_mode(1) # Active Mode
    hub.game.start()
    hub.broadcast_ws({"type": "status", "msg": f"Started {mode}"})
    return "OK"

@app.route('/stop')
async def stop_game(request):
    if hub.game:
        hub.game.stop()
        # Aborted games aren't scored; game_over clears hub.game and sends Standby
        hub.game_over(save=False)
        hub.broadcast_ws({"type": "status", "msg": "Stopped"})
        return "Stopped"
    return "No game running"

# --- Async ESP-NOW Listener ---
async def espnow_listener():
    # Use STA_IF for ESP-NOW (more robust), but keep AP running for Web Server
    # Note: STA must be active for this to work well on some ESP32/IDF versions
    e, wlan = init_espnow(mode=network.STA_IF)
    
    # Ensure AP is on the same channel (Channel 1)
    # This is often shared, but good to ensure
    ap = network.WLAN(network.AP_IF)
    try:
        ap.config(channel=WIFI_CHANNEL)
    except:
        pass # Some ports don't allow setting AP channel directly if STA is active

    hub.esp = e # Store for sending
    hub.wlan = wlan
    print(f"ESP-NOW Listener Active (STA Mode). Channel: {wlan.config('channel')}")
    
    while True:
        try:
            # Drain everything that arrived since the last pass
            while e.any():
                host, msg = e.recv(0)
                if msg:
                    hub.handle_packet(host, msg)
        except Exception as ex:
            # A bad packet or radio error must never kill the listener
            print("ESP-NOW listener error:")
            sys.print_exception(ex)
        await asyncio.sleep_ms(10)

def log_memory():
    # Python heap + the IDF heap that WiFi/ESP-NOW/sockets allocate from.
    # The Python heap grows into the IDF heap and never gives memory back.
    gc.collect()
    try:
        import esp32
        idf = sum(h[1] for h in esp32.idf_heap_info(esp32.HEAP_DATA))
    except (ImportError, AttributeError):
        idf = -1
    print(f"MEM py_free={gc.mem_free()} idf_free={idf} clients={len(connected_clients)} nodes={len(hub.available_nodes)}")

# --- Node heartbeat check ---
async def node_monitor():
    seconds = 0
    while True:
        try:
            hub.check_nodes()
            if seconds % 60 == 5:
                log_memory()
        except Exception as ex:
            print("Node monitor error:")
            sys.print_exception(ex)
        seconds += 1
        await asyncio.sleep(1)

# --- Async Game Tick ---
async def game_loop():
    while True:
        if hub.game:
            try:
                hub.game.tick()
            except Exception as ex:
                # Abort the broken game instead of freezing with targets lit
                print("Game tick error, aborting game:")
                sys.print_exception(ex)
                try:
                    hub.game_over(save=False)
                    hub.broadcast_ws({"type": "status", "msg": "GAME ERROR"})
                except Exception as ex2:
                    sys.print_exception(ex2)
                    hub.game = None
        await asyncio.sleep_ms(100)

# --- Main Entry ---
def setup_wifi():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
    print(f"AP: {AP_SSID} IP: 192.168.4.1")

def start_tasks():
    asyncio.create_task(espnow_listener())
    asyncio.create_task(game_loop())
    asyncio.create_task(node_monitor())

async def main():
    setup_wifi()
    
    start_tasks()
    
    # Start Server
    print("Starting Server...")
    await app.start_server(port=80, debug=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as ex:
        # Crash outside the guarded loops: log, then reboot instead of sitting
        # at the REPL. Ctrl-C (KeyboardInterrupt) is not an Exception, so
        # mpremote can still stop the program.
        sys.print_exception(ex)
        time.sleep(3)
        machine.reset()
