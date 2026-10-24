import time
import random

from game_engine import GameMode


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
        self.last_hit_node = None
        self.next_spawn_time = 0  # no new target before this (spawn delay after a hit)
        self.next_refresh_time = 0

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
        self.last_hit_node = None
        
        self.next_setup_action = time.ticks_ms()
        self.engine.broadcast_ws({"type": "score", "value": 0})
        print(f"Time Attack+ Init: {self.difficulty}, {self.duration_ms/1000}s")

    def stop(self):
        self.state = "FINISHED"
        self.engine.broadcast_led(0, 0, 0)

    def on_node_lost(self, node_id):
        # A dead target can't be hit; forget it so the scheduler lights another
        self.active_targets.pop(node_id, None)
        self.spawn_history.pop(node_id, None)

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
                    # Restore active targets
                    for nid in self.active_targets:
                        self.engine.send_node_cmd(nid, 255, 0, 0)

            self.scheduler_tick(now)

            # Re-send red to lit targets every 2 s. The unicast is ACKed, so a
            # target that died while lit is noticed (and replaced) within ~3 s
            # instead of after the 15 s heartbeat timeout; a lost LED command
            # is repaired too.
            if time.ticks_diff(now, self.next_refresh_time) >= 0:
                self.next_refresh_time = time.ticks_add(now, 2000)
                for nid in list(self.active_targets):
                    self.engine.send_node_cmd(nid, 255, 0, 0)
            
            # Combo Expiry (4s timeout)
            if self.combo > 0:
                if time.ticks_diff(now, self.last_hit_time) > 4000:
                    self.combo = 0
                    print("Combo Expired")


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
        self.next_spawn_time = self.game_start_time

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
        
        # 2. Spawn needed? Not until the spawn delay after the last hit
        needed = min_active - current_active
        if needed > 0 and time.ticks_diff(now, self.next_spawn_time) >= 0:
            for _ in range(needed):
                self.spawn_weighted_node(now)

    def spawn_weighted_node(self, now):
        free = [n for n in self.engine.available_nodes if n not in self.active_targets]
        # No-Repeat Rule: the next spawn can't be the node that was just hit.
        # With 2 nodes (A lit, B just hit) nothing spawns until A is hit.
        available = [n for n in free if n != self.last_hit_node]
        if not available and not self.active_targets:
            # Only one node in play: it has to come back, after the spawn delay
            available = free

        if not available: return
        
        # Calculate weights: Higher weight if lower spawn_history
        # Simple inversion: Max history - current history + 1
        # Check if history dict contains all avail nodes
        # A node that joined mid-game starts level with the least-used node,
        # instead of 0 (which would make it light up far more often)
        floor = min(self.spawn_history.values()) if self.spawn_history else 0
        for n in available:
            if n not in self.spawn_history: self.spawn_history[n] = floor
            
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
        
        self.spawn_history[chosen] += 1
        self.last_spawn_time = now
        self.activate_node(chosen)

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
            
            # Spawn Delay before the next target (PRD 5.2)
            # Stage 0: 1.2s, Stage 1: 0.8s, Stage 2+: 0.5s
            stage_delays = {0: 1.2, 1: 0.8}
            delay = int(stage_delays.get(self.intensity_stage, 0.5) * 1000)
            self.next_spawn_time = time.ticks_add(now, delay)
            # spawn_weighted_node won't pick this node next (No-Repeat Rule)
            self.last_hit_node = node_id
            
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
                # "Timer continues, but no targets spawn": tick() skips the
                # scheduler until the freeze ends
                self.freeze_end_time = time.ticks_add(now, 1000)
                self.engine.broadcast_led(255, 140, 0) # Orange
                
                print(f"Penalty! Score: {self.score} FREEZE!")
                self.engine.broadcast_ws({"type": "score", "value": self.score})

    def finish_game(self):
        print(f"Time Attack+ Finish. Score:{self.score} Hits:{self.hits} MaxCombo:{self.max_combo}")
        self.state = "FINISHED"
        
        # 10s Blue cooldown
        self.engine.broadcast_led(0, 0, 255)
        # Blue ON, hub handles cleanup (no sleep: this runs on the event loop)
        
        self.engine.broadcast_ws({"type": "status", "msg": "GAME OVER"})
        self.engine.game_over()
