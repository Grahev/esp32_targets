import time
import sys
import os

# Add hub to path to import game_engine
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'hub')))

try:
    from game_engine import TimeAttackPlus
except ImportError:
    # If not found, try direct import assuming we are at root or something
    # But since we are creating this file, we know where it is.
    # Let's mock the engine first since we might not run this in the actual env
    pass

class MockEngine:
    def __init__(self):
        self.available_nodes = [1, 2, 3, 4]
        self.ws_messages = []
        self.led_broadcasts = []
        self.node_cmds = []
        self.game_over_called = False

    def broadcast_ws(self, msg):
        self.ws_messages.append(msg)
        # print(f"WS: {msg}")

    def broadcast_led(self, r, g, b):
        self.led_broadcasts.append((r, g, b))
        # print(f"LED Broadcast: {r, g, b}")

    def send_node_cmd(self, node_id, r, g, b):
        self.node_cmds.append((node_id, r, g, b))
        # print(f"Node {node_id} Cmd: {r, g, b}")

    def game_over(self):
        self.game_over_called = True
        print("Game Over")

# Mock time.ticks_ms and related since we are running on PC potentially
# If running in python (not micropython), time.ticks_ms doesn't exist.
if not hasattr(time, 'ticks_ms'):
    def ticks_ms():
        return int(time.time() * 1000)
    def ticks_add(t, d):
        return t + d
    def ticks_diff(t1, t2):
        return t1 - t2
    
    time.ticks_ms = ticks_ms
    time.ticks_add = ticks_add
    time.ticks_diff = ticks_diff

# Now import game_engine or copy the class if import fails (simple mock env)
# Since I can't guarantee import works easily without file structure, I will depend on the file existing at `hub/game_engine.py`
# I will try to load it dynamically.

import importlib.util
spec = importlib.util.spec_from_file_location("game_engine", "hub/game_engine.py")
game_engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game_engine)
TimeAttackPlus = game_engine.TimeAttackPlus

def run_test():
    engine = MockEngine()
    game = TimeAttackPlus(engine, duration_min=1, difficulty="Normal")
    
    print("--- Test Start ---")
    game.start()
    
    # 1. Setup Phase
    # Should pulse 3x Yellow, 1x Green
    print("Simulating Setup...")
    start_time = time.ticks_ms()
    while game.state == "SETUP":
        game.tick()
        time.sleep(0.01) # fast forward
        if time.ticks_diff(time.ticks_ms(), start_time) > 10000:
            print("TIMEOUT in SETUP")
            break
            
    print(f"Setup Complete. State: {game.state}")
    
    # Check Initial Spawn: Should be RED (255, 0, 0)
    # Check node commands
    last_cmd = engine.node_cmds[-1]
    print(f"Initial Spawn Cmd: {last_cmd}")
    if last_cmd[1:] == (255, 0, 0):
        print("PASS: Initial Spawn is RED.")
    else:
        print(f"FAIL: Initial Spawn is {last_cmd[1:]}")

    # 2. Gameplay - Score Test
    # Active nodes
    current_active = list(game.active_targets.keys())[0]
    print(f"Active Node: {current_active}")
    
    # Hit quickly (< 750ms)
    time.sleep(0.1) # 100ms
    game.on_hit(current_active)
    
    # Check Score: Should be 10 + 1 (base?) -> PRD says "+10 pts (Elite)". Code: points = 10.
    # Wait, code says `if rt < 750: points = 10`. Base points removed? 
    # Let's check logic:
    # `points = 0` ... `if rt < 750: points = 10` ... `score += points`.
    # Yes, base points were removed in my edit.
    
    print(f"Score after Elite Hit: {game.score}")
    if game.score == 10:
        print("PASS: Elite Score correct.")
    else:
        print(f"FAIL: Elite Score is {game.score}, expected 10.")
        
    game.tick() # Process respawn queue
    
    # 3. Combo Test
    # Need 3 hits to start multiplier.
    # Hit 2 (Standard)
    time.sleep(0.2) # Wait for Global Mask (150ms) to clear
    
    # Force spawn
    while not game.active_targets:
        game.tick()
        time.sleep(0.01)
        
    current = list(game.active_targets.keys())[0]
    # Simulate 800ms delay
    game.active_targets[current] = time.ticks_ms() - 800
    game.on_hit(current) 
    # Score: 5 pts. Total: 15. Combo: 2.
    
    # Hit 3 (Slow)
    time.sleep(0.2)
    while not game.active_targets: game.tick(); time.sleep(0.01)
    current = list(game.active_targets.keys())[0]
    game.active_targets[current] = time.ticks_ms() - 1500
    game.on_hit(current)
    # Score: 2 pts. Total: 17. Combo: 3.
    
    # Hit 4 (Elite with Multiplier)
    time.sleep(0.2)
    while not game.active_targets: game.tick(); time.sleep(0.01)
    current = list(game.active_targets.keys())[0]
    game.active_targets[current] = time.ticks_ms() - 100
    game.on_hit(current)
    # Score: 10 * 1.5 = 15. Total: 17 + 15 = 32.
    
    print(f"Score after 4 hits: {game.score}")
    if game.score == 32:
        print("PASS: Combo Multiplier logic correct.")
    else:
        print(f"FAIL: Score is {game.score}, expected 32.")

    # 4. Penalty Freeze Test
    print("Testing Penalty...")
    time.sleep(0.2) # Clear mask
    inactive_node = [n for n in engine.available_nodes if n not in game.active_targets][0]
    game.on_hit(inactive_node)
    
    # Score: -15. Total: 17.
    # Freeze active?
    print(f"Score after Penalty: {game.score}")
    if game.freeze_end_time > time.ticks_ms():
        print("PASS: Freeze timer set.")
    else:
        print("FAIL: Freeze timer not set.")
        
    # Check Orange Broadcast
    last_led = engine.led_broadcasts[-1]
    if last_led == (255, 140, 0):
        print("PASS: Orange LED Broadcast.")
    else:
        print(f"FAIL: LED Broadcast is {last_led}")
        
    print("--- Test End ---")

if __name__ == "__main__":
    run_test()
