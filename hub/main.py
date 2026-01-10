import time
import network
import uasyncio as asyncio
from machine import Pin
import ujson as json

# Libraries
from common.espnow_utils import init_espnow, unpack_message, pack_command, MSG_TYPE_ANNOUNCE, MSG_TYPE_HIT
from microdot_asyncio import Microdot, Response, send_file
from microdot_websocket import with_websocket
from game_engine import GameMode, TimeAttackPlus, ZombieMode, MemoryPatterns

# --- Configuration ---
AP_SSID = "Airsoft-Master"

# --- Globals ---
app = Microdot()
game_engine = None # Placeholder class wrapper if needed
connected_clients = []

# --- System Class ---
class HUB_SYSTEM:
    def __init__(self):
        self.nodes = set()
        self.node_macs = {} # Map ID -> MAC
        self.esp = None
        self.game = None
        self.wlan = None 
        self.available_nodes = [] 

    def broadcast_ws(self, msg_dict):
        msg_json = json.dumps(msg_dict)
        for p in connected_clients:
            try:
                asyncio.create_task(p.send(msg_json))
            except:
                pass
    
    def register_node(self, node_id, mac):
        # Update MAC if changed or new
        if node_id not in self.node_macs or self.node_macs[node_id] != mac:
            self.node_macs[node_id] = mac
            print(f"Registered Node {node_id} MAC: {mac}")
            try:
                self.esp.add_peer(mac)
            except:
                pass # Peer might exist
        
        # Add to available list
        if node_id not in self.available_nodes:
            self.available_nodes.append(node_id)
            self.available_nodes.sort()
            print(f"Node {node_id} added to pool. Total: {len(self.available_nodes)}")
            self.broadcast_ws({"type": "status", "msg": f"Node {node_id} Joined"})

    def on_hit(self, node_id, voltage, mac):
        print(f"HIT: Node {node_id}")
        self.nodes.add(node_id)
        
        # Ensure registered
        self.register_node(node_id, mac)
            
        if self.game:
            self.game.on_hit(node_id)
        
        self.broadcast_ws({"type": "hit", "node_id": node_id, "time": time.ticks_ms()})

    def send_node_cmd(self, node_id, r, g, b):
        if self.esp and node_id in self.node_macs:
            mac = self.node_macs[node_id]
            cmd = pack_command(1, r, g, b) # CMD 1 = Set LED
            try:
                self.esp.send(mac, cmd)
                print(f"Sent LED {r},{g},{b} to {node_id}")
            except Exception as e:
                print(f"Send Error: {e}")
        else:
            print(f"Cannot send to Node {node_id} (Unknown MAC)")

    def broadcast_led(self, r, g, b):
        if self.esp:
            cmd = pack_command(1, r, g, b)
            # 1. Try Broadcast
            broadcast = b'\xff' * 6
            try:
                self.esp.add_peer(broadcast)
            except:
                pass
            try:
                self.esp.send(broadcast, cmd)
            except Exception as e:
                print(f"Broadcast Error: {e}")
            
            # 2. Unicast to all known nodes (Fallback)
            for nid, mac in self.node_macs.items():
                try:
                    self.esp.send(mac, cmd)
                    print(f"Unicast LED {r},{g},{b} to {nid}")
                except:
                    pass

    def game_over(self):
        print("GAME OVER")
        if self.game:
            if self.game.name == "Time Attack+":
                self.save_score(self.game)
            self.game = None
        self.broadcast_ws({"type": "status", "msg": "GAME OVER"})
        # Send updated leaderboard
        self.broadcast_ws({"type": "leaderboard", "data": self.get_leaderboard()})

    def save_score(self, game_obj):
        try:
            scores = self.get_leaderboard()
            
            # Add new
            duration_min = game_obj.duration_ms / 60000.0
            new_score = {
                "hits": game_obj.hits,
                "score": game_obj.score,
                "max_combo": game_obj.max_combo,
                "penalties": game_obj.penalty_count,
                "difficulty": game_obj.difficulty,
                "duration_min": duration_min,
                # Avoid div by zero
                "hpm": game_obj.hits / duration_min if duration_min > 0 else 0,
                "hps": game_obj.hits / (game_obj.duration_ms / 1000.0) if game_obj.duration_ms > 0 else 0,
                "avg_rt": (sum(game_obj.reaction_times)/len(game_obj.reaction_times)) if game_obj.reaction_times else 0
            }
            scores.append(new_score)
            
            # Sort by Score desc
            scores.sort(key=lambda x: x['score'], reverse=True)
            scores = scores[:20] # Keep Top 20 for mixed difficulties
            
            with open('scores_time_attack.json', 'w') as f:
                json.dump(scores, f)
            print("Score Saved")
        except Exception as e:
            print(f"Save Error: {e}")

    def get_leaderboard(self):
        try:
            with open('scores_time_attack.json', 'r') as f:
                return json.load(f)
        except:
            return []

hub = HUB_SYSTEM()

# --- Web Server Routes ---
@app.route('/')
async def index(request):
    return send_file('hub/static/index.html')

@app.route('/api/leaderboard')
async def get_leaderboard_route(request):
    return json.dumps(hub.get_leaderboard())

@app.route('/ws')
async def websocket_handler(request):
    # Manual WebSocket upgrade to avoid decorator issues with async
    from microdot_websocket import WebSocket
    ws = WebSocket(request)
    await ws.handshake()
    print("WS Connected")
    connected_clients.append(ws)
    # Send initial leaderboard
    await ws.send(json.dumps({"type": "leaderboard", "data": hub.get_leaderboard()}))
    try:
        while True:
            msg = await ws.receive()
    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)

@app.route('/start')
async def start_game(request):
    mode = request.args.get('mode', 'TimeAttack')
    print(f"Starting {mode}")
    
    if not hub.available_nodes:
        return "No Nodes Connected"
    
    if mode == 'TimeAttack':
        duration = int(request.args.get('duration', 1))
        delay = float(request.args.get('delay', 1.0))
        diff = request.args.get('difficulty', 'Normal')
        pen = (request.args.get('penalties', 'true') == 'true')
        
        hub.game = TimeAttackPlus(hub, duration_min=duration, difficulty=diff, penalties=pen, respawn_delay=delay) 
    elif mode == 'Zombie':
        hub.game = ZombieMode(hub)
    elif mode.startswith('Memory'):
        hub.game = MemoryPatterns(hub, variance="Hard" if "Hard" in mode else "Standard")
    
    if hub.game:
        hub.game.start()
        hub.broadcast_ws({"type": "status", "msg": f"Started {mode}"})
    
    return "OK"

@app.route('/stop')
async def stop_game(request):
    if hub.game:
        hub.game.stop()
        hub.game = None
        hub.broadcast_ws({"type": "status", "msg": "Stopped"})
    return "Stopped"

# --- Async ESP-NOW Listener ---
async def espnow_listener():
    # Use STA_IF for ESP-NOW (more robust), but keep AP running for Web Server
    # Note: STA must be active for this to work well on some ESP32/IDF versions
    e, wlan = init_espnow(mode=network.STA_IF)
    
    # Ensure AP is on the same channel (Channel 1)
    # This is often shared, but good to ensure
    ap = network.WLAN(network.AP_IF)
    try:
        ap.config(channel=1)
    except:
        pass # Some ports don't allow setting AP channel directly if STA is active

    hub.esp = e # Store for sending
    hub.wlan = wlan
    print(f"ESP-NOW Listener Active (STA Mode). Channel: {wlan.config('channel')}")
    
    while True:
        if e.any():
            host, msg = e.recv()
            if msg:
                # print(f"DEBUG: Msg from {host} len={len(msg)}")
                try:
                    data = unpack_message(msg)
                    if data:
                        node_id, batt, hit, msg_type = data
                        # print(f"DEBUG: Unpacked -> ID:{node_id} Type:{msg_type}")
                        
                        if msg_type == MSG_TYPE_ANNOUNCE:
                            hub.register_node(node_id, host)
                        elif msg_type == MSG_TYPE_HIT:
                            if hit:
                                hub.on_hit(node_id, batt, host)
                    else:
                        print("DEBUG: Unpack returned None")
                except Exception as ex:
                    print(f"DEBUG: Unpack Error: {ex}")
        await asyncio.sleep_ms(10)

# --- Async Game Tick ---
async def game_loop():
    while True:
        if hub.game:
            hub.game.tick()
        await asyncio.sleep_ms(100)

# --- Main Entry ---
def setup_wifi():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    ap.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
    print(f"AP: {AP_SSID} IP: 192.168.4.1")

async def main():
    setup_wifi()
    
    # Start Tasks
    asyncio.create_task(espnow_listener())
    asyncio.create_task(game_loop())
    
    # Start Server
    print("Starting Server...")
    await app.start_server(port=80, debug=True)

if __name__ == "__main__":
    asyncio.run(main())
