import time
import network
import uasyncio as asyncio
from machine import Pin
import ujson as json

# Libraries
from common.espnow_utils import init_espnow, unpack_message, pack_command
from microdot_asyncio import Microdot, Response, send_file
from microdot_websocket import with_websocket
from game_engine import GameMode, TimeAttack, ZombieMode, MemoryPatterns

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
        self.available_nodes = [1] 

    def broadcast_ws(self, msg_dict):
        msg_json = json.dumps(msg_dict)
        for p in connected_clients:
            try:
                asyncio.create_task(p.send(msg_json))
            except:
                pass

    def on_hit(self, node_id, voltage, mac):
        print(f"HIT: Node {node_id}")
        self.nodes.add(node_id)
        
        # Store MAC for return comms
        if node_id not in self.node_macs:
            self.node_macs[node_id] = mac
            # Try add peer just in case (ignore if exists)
            try:
                self.esp.add_peer(mac)
            except:
                pass

        if node_id not in self.available_nodes:
            self.available_nodes.append(node_id)
            
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
            self.game = None
        self.broadcast_ws({"type": "status", "msg": "GAME OVER"})

hub = HUB_SYSTEM()

# --- Web Server Routes ---
@app.route('/')
async def index(request):
    return send_file('hub/static/index.html')

@app.route('/ws')
async def websocket_handler(request):
    # Manual WebSocket upgrade to avoid decorator issues with async
    from microdot_websocket import WebSocket
    ws = WebSocket(request)
    await ws.handshake()
    print("WS Connected")
    connected_clients.append(ws)
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
    
    if mode == 'TimeAttack':
        hub.game = TimeAttack(hub) 
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
                        node_id, batt, hit, _ = data
                        # print(f"DEBUG: Unpacked -> ID:{node_id} Hit:{hit}")
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
