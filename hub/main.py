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

# ... (Previous Code)

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

# ... (Previous Routes)

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
