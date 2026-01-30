import time
import network
import uasyncio as asyncio
from machine import Pin
import ujson as json

# Libraries
from common.espnow_utils import init_espnow, unpack_message, pack_command, MSG_TYPE_ANNOUNCE, MSG_TYPE_HIT
from microdot_asyncio import Microdot, Response, send_file
from microdot_websocket import with_websocket
from game_engine import GameMode, TimeAttackPlus, TheBreach


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
        self.available_nodes = [] 
        self.node_battery = {} # Map ID -> Voltage 
        self.sys_mode = 0 # 0=Idle, 1=Active, 2=Standby
        self._idle_task = None
        
    def set_system_mode(self, mode):
        # 0=Idle, 1=Active, 2=Standby
        print(f"Setting System Mode: {mode}")
        self.sys_mode = mode
        self.broadcast_command(2, mode, 0, 0) # CMD 2 = Set Mode

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
        for p in connected_clients:
            try:
                asyncio.create_task(p.send(msg_json))
            except:
                pass
    
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

    def register_node(self, node_id, mac, voltage=None, percent=0, charging=False):
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
        
        if voltage is not None:
            self.update_battery(node_id, voltage, percent, charging)
            
        # Sync new node to current mode (unicast)
        # We need to construct a unicast packet for Set Mode
        # Re-use send_node_cmd logic but for Mode
        self.send_node_mode(node_id, self.sys_mode)

    def send_node_mode(self, node_id, mode):
        if self.esp and node_id in self.node_macs:
             mac = self.node_macs[node_id]
             cmd = pack_command(2, mode, 0, 0) # 2=Set Mode
             try:
                 self.esp.send(mac, cmd)
             except:
                 pass

    def on_hit(self, node_id, voltage, percent, charging, mac):
        print(f"HIT: Node {node_id} V={voltage:.2f} P={percent}% C={charging}")
        self.nodes.add(node_id)
        
        # Update battery
        self.update_battery(node_id, voltage, percent, charging)
        
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

    def broadcast_command(self, cmd_id, r, g, b):
        if self.esp:
            cmd = pack_command(cmd_id, r, g, b)
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
                except:
                    pass

    def broadcast_led(self, r, g, b):
        self.broadcast_command(1, r, g, b)

    def game_over(self):
        print("GAME OVER")
        if self.game:
            if self.game.name == "Time Attack+":
                self.save_score(self.game, "TimeAttack")
            elif self.game.name == "The Breach":
                self.save_score(self.game, "TheBreach")
            
            # Capture mode before clearing
            mode_name = "TimeAttack" if self.game.name == "Time Attack+" else "TheBreach"
            self.game = None
            
            self.broadcast_ws({"type": "status", "msg": "GAME OVER"})
            # Send updated leaderboard for that mode
            self.broadcast_ws({"type": "leaderboard", "mode": mode_name, "data": self.get_leaderboard(mode_name)})
            
            # Switch to Standby, then schedule Idle
            self.set_system_mode(2)
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
            
            with open(filename, 'w') as f:
                json.dump(scores, f)
            print(f"Score Saved to {filename}")
        except Exception as e:
            print(f"Save Error: {e}")

    def get_leaderboard(self, mode="TimeAttack"):
        filename = f'scores_{mode}.json'
        try:
            with open(filename, 'r') as f:
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
    # Send initial leaderboards (Both?)
    # Frontend can filter, or request. Let's send TimeAttack as default.
    await ws.send(json.dumps({"type": "leaderboard", "mode": "TimeAttack", "data": hub.get_leaderboard("TimeAttack")}))
    await ws.send(json.dumps({"type": "leaderboard", "mode": "TheBreach", "data": hub.get_leaderboard("TheBreach")}))
    
    # Send all current battery levels
    for nid, data in hub.node_battery.items():
        # Handle backward compatibility if dict was somehow old (unlikely but safe)
        if isinstance(data, dict):
            await ws.send(json.dumps({
                "type": "battery", 
                "node_id": nid, 
                "voltage": round(data['voltage'], 2),
                "percent": data.get('percent', 0),
                "charging": data.get('charging', False)
            }))

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
        # For testing without nodes, we might want to bypass, but strictly:
        return "No Nodes Connected"
    
    if mode == 'TimeAttack':
        duration = int(request.args.get('duration', 1))
        delay = float(request.args.get('delay', 1.0))
        diff = request.args.get('difficulty', 'Normal')
        pen = (request.args.get('penalties', 'true') == 'true')
        
        hub.game = TimeAttackPlus(hub, duration_min=duration, difficulty=diff, penalties=pen, respawn_delay=delay) 
    elif mode == 'TheBreach':
        # Default start level 1
        hub.game = TheBreach(hub, start_level=1)
    
    if hub.game:
        hub.cancel_idle_timer() # Cancel pending idle if any
        hub.set_system_mode(1) # Active Mode
        hub.game.start()
        hub.broadcast_ws({"type": "status", "msg": f"Started {mode}"})
    
    return "OK"

@app.route('/stop')
async def stop_game(request):
    if hub.game:
        hub.game.stop()
        # game.stop() calls game_over() which handles mode switch?
        # Typically separate. TimeAttack calls hub.game_over().
        # Manual stop might not trigger it if game logic is simple?
        # Assuming manual stop also clears game:
        hub.game = None
        hub.game_over() # Trigger Cleanup & Standby logic
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
                        # Updated Unpack: <ID><BATT_V><BATT_P><HIT><MSG_TYPE><CHARGING>
                        if len(data) == 6:
                            node_id, batt, pct, hit, msg_type, chg = data
                            charging = bool(chg)
                            
                            if msg_type == MSG_TYPE_ANNOUNCE:
                                hub.register_node(node_id, host, batt, pct, charging)
                            elif msg_type == MSG_TYPE_HIT:
                                if hit:
                                    hub.on_hit(node_id, batt, pct, charging, host)
                        elif len(data) == 4:
                             # Legacy Fallback (if mix of nodes)
                            node_id, batt, hit, msg_type = data
                            if msg_type == MSG_TYPE_ANNOUNCE:
                                hub.register_node(node_id, host, batt)
                            elif msg_type == MSG_TYPE_HIT:
                                if hit:
                                    # Fallback on_hit needs signature match? 
                                    # Python accepts keyword args but here we called positional.
                                    # Better to update on_hit to defaults?
                                    # Or just pass 0/False
                                    hub.on_hit(node_id, batt, 0, False, host)
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
