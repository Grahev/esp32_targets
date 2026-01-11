import time
import random

class GameMode:
    def __init__(self, engine):
        self.engine = engine
        self.name = "Generic"

    def start(self):
        pass

    def stop(self):
        pass

    def on_hit(self, node_id, damage=1):
        pass

    def tick(self):
        """Called every loop to handle timing/timeouts"""
        pass

class DifficultyConfig:
    # Key: Difficulty Level -> [Activation Speed Factor/Seconds, Min Active Targets]
    # Curve: S0, S1, S2, S3, S4, S5 (0s, 30s, 60s, 90s, 120s, 150s+)
    # Values are seconds (multipliers if base_delay=1.0s)
    SPEED_CURVE = {
        "Easy":    [1.8, 1.7, 1.6, 1.5, 1.4, 1.3],
        "Normal":  [1.6, 1.5, 1.4, 1.3, 1.2, 1.0],
        "Hard":    [1.3, 1.2, 1.1, 1.0, 0.9, 0.8],
        "Extreme": [1.1, 1.0, 0.9, 0.8, 0.7, 0.6]
    }
    
    # Min Targets
    MIN_TARGET_CURVE = {
        "Easy":    [1, 1, 1, 1, 1, 2],
        "Normal":  [1, 1, 2, 2, 2, 2],
        "Hard":    [1, 1, 2, 2, 2, 3],
        "Extreme": [2, 2, 2, 3, 3, 3]
    }

    PENALTIES = {"Easy": -1, "Normal": -1, "Hard": -2, "Extreme": -5}

class TimeAttackPlus(GameMode):
    def __init__(self, engine, duration_min=1, difficulty="Normal", penalties=True, respawn_delay=1.0):
        super().__init__(engine)
        self.name = "Time Attack+"
        self.duration_ms = duration_min * 60 * 1000
        self.base_respawn_delay_ms = int(respawn_delay * 1000)
        self.difficulty = difficulty
        self.penalties_enabled = penalties
        
        # State
        self.state = "SETUP" 
        self.score = 0
        self.hits = 0
        self.penalty_count = 0
        self.combo = 0
        self.max_combo = 0
        self.reaction_times = []
        
        self.game_start_time = 0
        self.game_end_time = 0
        self.last_hit_time = 0
        
        # Tracking
        self.active_targets = {} # {node_id: activation_time_ms}
        self.spawn_history = {}  # {node_id: count} for weighting
        self.respawn_queue = []  # List of (wake_time, node_id)
        
        self.intensity_stage = 0
        self.last_spawn_time = 0
        
        # Setup Sequence
        self.setup_step = 0
        self.next_setup_action = 0

    def start(self):
        self.state = "SETUP"
        self.setup_step = 0
        self.score = 0
        self.hits = 0
        self.combo = 0
        self.max_combo = 0
        self.penalty_count = 0
        self.reaction_times = []
        self.spawn_history = {nid: 0 for nid in self.engine.available_nodes}
        self.active_targets = {}
        
        self.next_setup_action = time.ticks_ms()
        self.engine.broadcast_ws({"type": "score", "value": 0})
        print(f"Time Attack+ Init: {self.difficulty}, {self.duration_ms/1000}s")

    def stop(self):
        self.state = "FINISHED"
        self.engine.broadcast_led(0, 0, 0)

    def tick(self):
        now = time.ticks_ms()
        
        if self.state == "SETUP":
            if time.ticks_diff(now, self.next_setup_action) >= 0:
                self.handle_setup(now)
                
        elif self.state == "PLAYING":
            # Check Timer
            remaining = time.ticks_diff(self.game_end_time, now)
            if remaining <= 0:
                self.finish_game()
                return
            
            # Broadcast Timer (approx every 1s)
            if remaining % 1000 < 150: 
                self.engine.broadcast_ws({"type": "timer", "value": int(remaining/1000)})

            self.update_intensity(now)
            
            # Freeze Logic
            if self.freeze_end_time > 0:
                if time.ticks_diff(self.freeze_end_time, now) > 0:
                    # Still frozen, ensure Orange flash is maintained (optional re-broadcast)
                    # For simple WS2812, 1 broadcast is enough usually, but to be safe we can skip spawn logic
                    return
                else:
                    self.freeze_end_time = 0
                    self.engine.broadcast_led(0, 0, 0) # Clear freeze

            self.scheduler_tick(now)
            
            # Combo Expiry (4s timeout)
            if self.combo > 0:
                if time.ticks_diff(now, self.last_hit_time) > 4000:
                    self.combo = 0
                    print("Combo Expired")
            
            # Respawn Logic
            for item in self.respawn_queue[:]:
                wake_time, node_id = item
                if time.ticks_diff(now, wake_time) >= 0:
                    self.activate_node(node_id)
                    self.respawn_queue.remove(item)

    def handle_setup(self, now):
        # 3x Yellow Pulse, 1x Green Blink
        step = self.setup_step
        if step < 6: 
            is_on = (step % 2 == 0)
            if is_on:
                self.engine.broadcast_led(255, 255, 0) # Yellow
                self.next_setup_action = time.ticks_add(now, 500)
            else:
                self.engine.broadcast_led(0, 0, 0)
                self.next_setup_action = time.ticks_add(now, 300)
            self.setup_step += 1
        elif step == 6: 
            self.engine.broadcast_led(0, 255, 0) # Green for "Ready"
            self.next_setup_action = time.ticks_add(now, 800)
            self.setup_step += 1
        elif step == 7: 
            self.engine.broadcast_led(0, 0, 0)
            self.start_game_play()

    def start_game_play(self):
        self.state = "PLAYING"
        self.game_start_time = time.ticks_ms()
        self.last_hit_time = self.game_start_time
        self.game_end_time = time.ticks_add(self.game_start_time, self.duration_ms)
        self.freeze_end_time = 0
        self.global_mask_end_time = 0

        self.engine.broadcast_ws({"type": "status", "msg": "GO!"})
        
        # Initial fill - 1 Node Red
        self.update_intensity(self.game_start_time)
        # Force 1 active target immediately for Start
        self.spawn_weighted_node(self.game_start_time)

    def update_intensity(self, now):
        elapsed_sec = time.ticks_diff(now, self.game_start_time) / 1000.0
        # Stages: 30s intervals
        stage = int(elapsed_sec / 30)
        if stage > 5: stage = 5
        self.intensity_stage = stage

    def scheduler_tick(self, now):
        # 1. Determine Min Active Targets
        curve = DifficultyConfig.MIN_TARGET_CURVE.get(self.difficulty, DifficultyConfig.MIN_TARGET_CURVE["Normal"])
        idx = min(self.intensity_stage, len(curve)-1)
        min_active = curve[idx]
        
        # Cap min_active to available nodes
        total_nodes = len(self.engine.available_nodes)
        if min_active > total_nodes: min_active = total_nodes
        
        current_active = len(self.active_targets)
        
        # 2. Spawn needed?
        needed = min_active - current_active
        if needed > 0:
            for _ in range(needed):
                self.spawn_weighted_node(now)

    def spawn_weighted_node(self, now):
        # Allow checking against last_hit_node if exists
        last_node = getattr(self, "last_hit_node", None)
        
        available = [n for n in self.engine.available_nodes 
                    if n not in self.active_targets and n != last_node]
        
        # If filtering last_node made list empty (e.g. 2 nodes total, 1 active, 1 just hit),
        # we might have to allow repeat or just wait. 
        # Requirement: "No-Repeat Rule: The next random spawn cannot be the node that was just hit."
        # If we only have 2 nodes, Node A is active, Node B just hit. 
        # A is active. B cannot be spawned. So no spawn. 
        # Wait for A to be hit. Then A becomes last_hit, B becomes valid. Correct.
        
        if not available: return
        
        # Calculate weights: Higher weight if lower spawn_history
        # Simple inversion: Max history - current history + 1
        # Check if history dict contains all avail nodes
        for n in available:
            if n not in self.spawn_history: self.spawn_history[n] = 0
            
        max_h = max(self.spawn_history.values()) if self.spawn_history else 0
        weights = [(max_h - self.spawn_history[n] + 1) for n in available]
        
        # Weighted Random Choice
        total_w = sum(weights)
        r = random.randint(1, total_w)
        upto = 0
        chosen = available[0]
        for i, w in enumerate(weights):
            upto += w
            if r <= upto:
                chosen = available[i]
                break
        
        self.activate_node(chosen)
        self.spawn_history[chosen] += 1
        self.last_spawn_time = now

    def activate_node(self, node_id):
        self.active_targets[node_id] = time.ticks_ms()
        self.engine.send_node_cmd(node_id, 255, 0, 0) # Red

    def on_hit(self, node_id, damage=1):
        if self.state != "PLAYING": return
        now = time.ticks_ms()
        
        # 1. Global Input Mask
        if self.global_mask_end_time > 0 and time.ticks_diff(self.global_mask_end_time, now) > 0:
            return # Ignore input

        if node_id in self.active_targets:
            # --- Valid Hit ---
            activation_time = self.active_targets.pop(node_id)
            self.engine.send_node_cmd(node_id, 0, 0, 0) # Off
            
            # Set Global Mask for 150ms
            self.global_mask_end_time = time.ticks_add(now, 150)

            # Record hit time for combo expiry
            self.last_hit_time = now

            # Reaction Time
            rt = time.ticks_diff(now, activation_time)
            self.reaction_times.append(rt)
            
            # Scoring
            points = 0
            
            # RT Bonus (Revised)
            # < 750ms: +10 (Elite)
            # 750-1400ms: +5 (Standard)
            # > 1400ms: +2 (Slow)
            if rt < 750: points = 10
            elif rt <= 1400: points = 5
            else: points = 2
            
            # Combo
            self.combo += 1
            if self.combo > self.max_combo: self.max_combo = self.combo
            
            # Combo Multiplier (Every 3 hits -> 1.5x on subsequent points)
            # "Every 3 successful hits ... triggers a 1.5x Multiplier on subsequent points"
            # Clarification: Does it apply to THIS hit or subsequent? Text says "subsequent points".
            # Assuming it implies a persistent multiplier state or just bonus points.
            # "triggers a 1.5x Multiplier on subsequent points" might mean a state change.
            # But usually "Combo BOonus" is simpler.
            # Let's interpret as: If combo > 3, apply 1.5x to THIS score (rewarding maintaining high combo).
            # OR logic: Hit 1, 2, 3... Hit 4 gets 1.5x.
            # Revised interpretation: If current combo > 3, mult = 1.5.
            
            multiplier = 1.0
            if self.combo > 3:
                multiplier = 1.5
            
            points = int(points * multiplier)

            self.score += points
            self.hits += 1
            
            print(f"Hit! Node:{node_id} RT:{rt}ms Combo:{self.combo} Pts:{points}")
            self.engine.broadcast_ws({"type": "score", "value": self.score})
            self.engine.broadcast_ws({"type": "hit", "node_id": node_id, "time": now})
            
            # Schedule Respawn
            # Stage 0: 1.2s, Stage 1: 0.8s, Stage 2: 0.5s
            stage_delays = {0: 1.2, 1: 0.8, 2: 0.5, 3: 0.5, 4: 0.5, 5: 0.5}
            base_delay = stage_delays.get(self.intensity_stage, 1.2)
            
            delay_max_ms = int(base_delay * 1000)
            # Randomize slightly? "Spawn Delay: 1.2s". Implies fixed or average. 
            # Existing code had random range. Let's keep it tight.
            delay = delay_max_ms
            
            wake_time = time.ticks_add(now, delay)
            
            # NO REPEAT Rule: Implemented in spawn_weighted_node (it chooses form available, we modify there)
            # Actually, to prevent "immediate" no-repeat, we just need to make sure the respawn queue 
            # doesn't just pick the same one if multiple are free? 
            # The logic "No-Repeat Rule: The next random spawn cannot be the node that was just hit."
            # is best handled in `spawn_weighted_node` by filtering out `last_hit_node` if needed.
            # But since we just popped `node_id` from `active_targets`, it IS available.
            # We will store `self.last_hit_node = node_id` and check in weighted spawn.
            self.last_hit_node = node_id

            self.respawn_queue.append((wake_time, node_id)) # This puts it back in rotation
            
        else:
            # --- Inactive Hit (Penalty) ---
            if self.penalties_enabled:
                # -15 Points
                # Freeze 1.0s (Orange)
                penalty = -15
                self.score += penalty 
                self.penalty_count += 1
                self.combo = 0 # Reset combo
                
                # Freeze Logic
                self.freeze_end_time = time.ticks_add(now, 1000)
                self.respawn_queue = [] # specific logic: "no targets spawn". 
                # Should we clear pending spawns? "Timer continues, but no targets spawn".
                # If we clear queue, nodes won't respawn. We should probably just DELAY them 
                # or prevent `scheduler_tick` from adding new ones.
                # Simplest: Input mask is already implied by freeze state checking in tick?
                # Actually tick check just handles LED.
                # We need to broadcast Orange NOW.
                self.engine.broadcast_led(255, 140, 0) # Orange
                
                print(f"Penalty! Score: {self.score} FREEZE!")
                self.engine.broadcast_ws({"type": "score", "value": self.score})

    def finish_game(self):
        print(f"Time Attack+ Finish. Score:{self.score} Hits:{self.hits} MaxCombo:{self.max_combo}")
        self.state = "FINISHED"
        
        # 10s Blue cooldown
        self.engine.broadcast_led(0, 0, 255) 
        time.sleep(0.1) # Small blocking ok? Prefer async task for fade out
        # Keeping it simple: Blue ON, Hub handles cleanup
        
        self.engine.broadcast_ws({"type": "status", "msg": "GAME OVER"})
        self.engine.game_over()

class ZombieMode(GameMode):
    def __init__(self, engine):
        super().__init__(engine)
        self.name = "Zombie"
        self.wave = 1
        self.active_zombies = {} # {id: {"start_time": t, "brightness": 0}}
        self.next_spawn = 0

    def start(self):
        self.wave = 1
        self.active_zombies = {}
        self.next_spawn = time.ticks_ms() + 1000
        print("Zombie Apocalypse Started")

    def tick(self):
        now = time.ticks_ms()
        # Spawn Logic
        if now > self.next_spawn:
            target = random.choice(self.engine.available_nodes)
            if target not in self.active_zombies:
                self.active_zombies[target] = {"start_time": now, "brightness": 0}
                self.next_spawn = now + max(500, 2000 - (self.wave * 100)) # Faster each wave
        
        # Update Brightness (Ramp)
        for zid, data in self.active_zombies.items():
            run_time = time.ticks_diff(now, data["start_time"])
            brightness = min(255, int(run_time / 2000 * 255)) # Fully bright in 2s
            if brightness >= 255:
                # Bitten!
                print("Player Bitten! Game Over.")
                self.engine.game_over()
                return
            
            if brightness != data["brightness"]:
                data["brightness"] = brightness
                # Send update to node (optimize to not flood)
                # self.engine.send_node_cmd(zid, brightness, 0, 0) # Red ramp

class MemoryPatterns(GameMode):
    def __init__(self, engine, variance="Standard"):
        super().__init__(engine)
        self.name = f"Memory {variance}"
        self.hard_mode = (variance == "Hard")
        self.sequence = []
        self.player_idx = 0
        self.showing_sequence = False
    
    def start(self):
        self.sequence = []
        self.next_round()
    
    def next_round(self):
        if self.hard_mode:
            # Completely new sequence
            length = len(self.sequence) + 1 if self.sequence else 1
            self.sequence = [random.choice(self.engine.available_nodes) for _ in range(length)]
        else:
            # Add one
            self.sequence.append(random.choice(self.engine.available_nodes))
        
        self.player_idx = 0
        self.show_sequence()

    def show_sequence(self):
        self.showing_sequence = True
        print(f"Watch: {self.sequence}")
        # Logic to play sequence on nodes
        # Async wait needed here usually
        self.showing_sequence = False # Placeholder

    def on_hit(self, node_id, damage=1):
        if self.showing_sequence: return
        
        expected = self.sequence[self.player_idx]
        if node_id == expected:
            print("Correct")
            self.player_idx += 1
            if self.player_idx >= len(self.sequence):
                print("Round Complete")
                self.next_round()
        else:
            print("WRONG! Game Over")
            self.engine.game_over()
