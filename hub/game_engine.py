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
    # Key: Difficulty Level -> [Activation Speed Factor, Min Active Targets]
    # Curve: S0, S1, S2, S3, S4, S5 (0s, 20s, 40s, 60s, 80s, 100s)
    # Factor is multiplier for Respawn Delay
    SPEED_CURVE = {
        "Easy":    [1.0, 0.95, 0.90, 0.85, 0.80, 0.75],
        "Normal":  [0.8, 0.70, 0.60, 0.55, 0.50, 0.45],
        "Hard":    [0.5, 0.45, 0.40, 0.35, 0.30, 0.25],
        "Extreme": [0.35, 0.30, 0.25, 0.20, 0.15, 0.12]
    }
    
    # Min Targets
    MIN_TARGET_CURVE = {
        "Easy":    [1, 1, 1, 1, 1, 2],
        "Normal":  [1, 1, 2, 2, 2, 3],
        "Hard":    [2, 2, 3, 3, 3, 3],
        "Extreme": [2, 2, 3, 3, 4, 4]
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
            self.scheduler_tick(now)
            
            # Respawn Logic
            for item in self.respawn_queue[:]:
                wake_time, node_id = item
                if time.ticks_diff(now, wake_time) >= 0:
                    self.activate_node(node_id)
                    self.respawn_queue.remove(item)

    def handle_setup(self, now):
        # 3x Orange Pulse, 1x Green Blink
        step = self.setup_step
        if step < 6: 
            is_on = (step % 2 == 0)
            if is_on:
                self.engine.broadcast_led(255, 140, 0) # Orange
                self.next_setup_action = time.ticks_add(now, 500)
            else:
                self.engine.broadcast_led(0, 0, 0)
                self.next_setup_action = time.ticks_add(now, 300)
            self.setup_step += 1
        elif step == 6: 
            self.engine.broadcast_led(0, 255, 0) # Green
            self.next_setup_action = time.ticks_add(now, 800)
            self.setup_step += 1
        elif step == 7: 
            self.engine.broadcast_led(0, 0, 0)
            self.start_game_play()

    def start_game_play(self):
        self.state = "PLAYING"
        self.game_start_time = time.ticks_ms()
        self.game_end_time = time.ticks_add(self.game_start_time, self.duration_ms)
        self.engine.broadcast_ws({"type": "status", "msg": "GO!"})
        
        # Initial fill
        self.update_intensity(self.game_start_time)
        self.scheduler_tick(self.game_start_time)

    def update_intensity(self, now):
        elapsed_sec = time.ticks_diff(now, self.game_start_time) / 1000.0
        # Stages at 0, 20, 40, 60, 80, 100
        stage = int(elapsed_sec / 20)
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
        available = [n for n in self.engine.available_nodes if n not in self.active_targets]
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
        
        if node_id in self.active_targets:
            # --- Valid Hit ---
            activation_time = self.active_targets.pop(node_id)
            self.engine.send_node_cmd(node_id, 0, 0, 0) # Off
            
            # Reaction Time
            rt = time.ticks_diff(now, activation_time)
            self.reaction_times.append(rt)
            
            # Scoring
            points = 1 # Base
            
            # RT Bonus
            rt_bonus = 0
            if rt <= 600: rt_bonus = 3
            elif rt <= 900: rt_bonus = 2
            elif rt <= 1400: rt_bonus = 1
            
            points += rt_bonus
            
            # Combo
            # Also relax combo reset slightly to match new pacing (e.g. 2s)
            if rt > 2000:
                self.combo = 0 # Slow response reset
            else:
                self.combo += 1
                if self.combo > self.max_combo: self.max_combo = self.combo
            
            # Combo Bonus (Every 5)
            if self.combo > 0 and self.combo % 5 == 0:
                points += 5
                
            self.score += points
            self.hits += 1
            
            print(f"Hit! Node:{node_id} RT:{rt}ms Combo:{self.combo} Pts:{points}")
            self.engine.broadcast_ws({"type": "score", "value": self.score})
            self.engine.broadcast_ws({"type": "hit", "node_id": node_id, "time": now})
            
            # Schedule Respawn
            # Delay affected by Difficulty Speed Curve
            spd_curve = DifficultyConfig.SPEED_CURVE.get(self.difficulty, DifficultyConfig.SPEED_CURVE["Normal"])
            idx = min(self.intensity_stage, len(spd_curve)-1)
            factor = spd_curve[idx]
            
            delay_max = int(self.base_respawn_delay_ms * factor)
            delay = random.randint(100, max(200, delay_max))
            
            wake_time = time.ticks_add(now, delay)
            self.respawn_queue.append((wake_time, node_id))
            
        else:
            # --- Inactive Hit (Penalty) ---
            if self.penalties_enabled:
                penalty = DifficultyConfig.PENALTIES.get(self.difficulty, -1)
                self.score += penalty # Penalty is negative
                self.penalty_count += 1
                self.combo = 0 # Reset combo
                print(f"Penalty! Score: {self.score}")
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
