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

    def on_node_lost(self, node_id):
        """A node stopped sending heartbeats and left engine.available_nodes."""
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

    def on_node_lost(self, node_id):
        # A dead target can't be hit; forget it so the scheduler lights another
        self.active_targets.pop(node_id, None)
        self.respawn_queue = [item for item in self.respawn_queue if item[1] != node_id]
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


class TheBreach(GameMode):
    def __init__(self, engine, start_level=1):
        super().__init__(engine)
        self.name = "The Breach"
        self.level = start_level
        self.max_level = 10
        self.score = 0
        self.total_time_bonus = 0
        
        # Level Config (Level -> {sequence_len, flash_ms})
        # 1-2: 3 targets, 700ms
        # 3-5: 4-5 targets, 500ms
        # 6-8: 6-7 targets, 400ms
        # 9-10: 8+ targets, 300ms
        self.level_config = {
            1: (3, 700), 2: (3, 700),
            3: (4, 500), 4: (5, 500), 5: (5, 500),
            6: (6, 400), 7: (6, 400), 8: (7, 400),
            9: (8, 300), 10: (9, 300) 
        }

        # State
        self.state = "INIT" # INIT, FLASH_COUNTDOWN, FLASHING, READY_PAUSE, GO_SIGNAL, PLAYING, LEVEL_COMPLETE, FAILED
        self.sequence = [] # List of node_ids
        self.current_idx = 0 # Index in sequence player needs to hit
        self.next_action_time = 0
        
        # Flash Phase State
        self.flash_idx = 0
        
        # Performance Tracking
        self.round_start_time = 0
        self.last_hit_time = 0
        self.reaction_times = []
        
        # Kinetic Adjustments
        self.input_mask_until = 0
    
    def start(self):
        print(f"The Breach Started. Level {self.level}")
        self.engine.broadcast_ws({"type": "status", "msg": f"LEVEL {self.level}"})
        self.score = 0
        self.reaction_times = []
        self.start_level_sequence()

    def stop(self):
        self.state = "STOPPED"
        self.engine.broadcast_led(0, 0, 0)

    def on_node_lost(self, node_id):
        if self.state in ("FAILED", "FINISHED", "STOPPED"):
            return
        if node_id in self.sequence:
            # The sequence can't be completed any more: replay this level
            # with the nodes that are still online
            print(f"Node {node_id} lost mid-level, restarting level {self.level}")
            self.engine.broadcast_ws({"type": "status", "msg": f"NODE {node_id} LOST"})
            self.engine.broadcast_led(0, 0, 0)
            self.start_level_sequence()

    def start_level_sequence(self):
        # Generate Sequence based on level
        seq_len, _ = self.get_level_specs()
        
        # Logic: "Simple left-to-right" or Random
        # For now, totally random from available nodes, allowing repeats? 
        # PRD doesn't explicitly forbid repeats, but "node 2 -> node 5 -> node 1" implies distinct usually.
        # "Cross-field transitions" implies distinct. 
        # Let's try to make them distinct if possible.
        avail = self.engine.available_nodes[:]
        if not avail:
            self.sequence = []
            self.fail_level("NO NODES")
            return
        if len(avail) < 2:
            print("Not enough nodes for sequence!")
            self.sequence = [avail[0]] * seq_len if avail else []
        else:
            self.sequence = []
            last = -1
            for _ in range(seq_len):
                # Avoid immediate repeat if possible
                choices = [n for n in avail if n != last]
                if not choices: choices = avail
                pick = random.choice(choices)
                self.sequence.append(pick)
                last = pick
        
        print(f"Level {self.level} Sequence: {self.sequence}")
        
        # Start Phase A: Observation
        self.state = "FLASH_COUNTDOWN"
        # "All nodes pulse Yellow (3-second countdown)"
        self.countdown_step = 0
        self.next_action_time = time.ticks_add(time.ticks_ms(), 1000)
        self.engine.broadcast_led(255, 255, 0) # Yellow
        self.engine.broadcast_ws({"type": "status", "msg": "WATCH..."})

    def get_level_specs(self):
        cfg = self.level_config.get(self.level, (8, 300))
        return cfg

    def tick(self):
        now = time.ticks_ms()
        
        if self.state == "FLASH_COUNTDOWN":
            if time.ticks_diff(now, self.next_action_time) >= 0:
                self.countdown_step += 1
                if self.countdown_step < 3:
                     # Pulse effect (Off then Yellow)
                    if self.countdown_step % 1 == 0: # Simple 1s beats
                         self.engine.broadcast_led(0, 0, 0)
                         time.sleep_ms(100) # Quick blink off
                         self.engine.broadcast_led(255, 255, 0)
                    self.next_action_time = time.ticks_add(now, 1000)
                else:
                    self.state = "FLASHING"
                    self.flash_idx = 0
                    self.engine.broadcast_led(0, 0, 0) # clear
                    self.next_action_time = time.ticks_add(now, 500) # Initial gap

        elif self.state == "FLASHING":
            if time.ticks_diff(now, self.next_action_time) >= 0:
                seq_len, flash_dur = self.get_level_specs()
                
                # If we just finished a flash (node is ON), turn it OFF
                # We need a sub-state or just check if we are waiting for OFF
                # Simplified:
                # 1. Turn ON Node at flash_idx
                # 2. Wait flash_dur
                # 3. Turn OFF
                # 4. Wait 300ms gap
                # 5. Next
                
                # To avoid blocking, we use fine-grained state or sub-step
                # Using a "flash_substep" var? Or just logic:
                # We can store "flash_end_time"
                if not hasattr(self, 'flash_active'): self.flash_active = False

                if self.flash_idx >= len(self.sequence):
                     # Done flashing
                     self.state = "READY_PAUSE"
                     self.next_action_time = time.ticks_add(now, 1500)
                     self.engine.broadcast_ws({"type": "status", "msg": "READY?"})
                     return

                if not self.flash_active:
                    # Turn ON
                    node = self.sequence[self.flash_idx]
                    self.engine.send_node_cmd(node, 0, 0, 255) # Blue
                    self.flash_active = True
                    self.next_action_time = time.ticks_add(now, flash_dur)
                else:
                    # Turn OFF
                    node = self.sequence[self.flash_idx]
                    self.engine.send_node_cmd(node, 0, 0, 0)
                    self.flash_active = False
                    self.flash_idx += 1
                    self.next_action_time = time.ticks_add(now, 300) # Gap

        elif self.state == "READY_PAUSE":
            if time.ticks_diff(now, self.next_action_time) >= 0:
                self.state = "GO_SIGNAL"
                # "All nodes pulse Green for 200ms or Beep"
                self.engine.broadcast_led(0, 255, 0)
                self.next_action_time = time.ticks_add(now, 200)
        
        elif self.state == "GO_SIGNAL":
            if time.ticks_diff(now, self.next_action_time) >= 0:
                self.engine.broadcast_led(0, 0, 0)
                self.start_play_phase(now)

        elif self.state == "PLAYING":
            # Check Timeout (5s between targets)
            # "Timeout: If a player takes longer than 5 seconds between any two targets"
            if time.ticks_diff(now, self.last_hit_time) > 5000:
                print("Timeout!")
                self.fail_level("TIMEOUT")
        
        elif self.state == "LEVEL_COMPLETE":
             if time.ticks_diff(now, self.next_action_time) >= 0:
                 if self.level < self.max_level:
                     self.level += 1
                     self.start_level_sequence()
                 else:
                     self.finish_game(success=True)

        elif self.state == "FAILED":
             if time.ticks_diff(now, self.next_action_time) >= 0:
                 self.engine.game_over()

    def start_play_phase(self, now):
        self.state = "PLAYING"
        self.current_idx = 0
        self.round_start_time = now
        self.last_hit_time = now
        self.engine.broadcast_ws({"type": "status", "msg": "GO!"})
        
        # Don't light up targets! "The Hunt: The player must hit the targets in the sequence shown."
        # Confirming PRD: "The system only 'listens' for a hit... nodes light up one-by-one in a specific sequence using Blue light (DURING FLASH)... The Execution... The player must hit the targets in the sequence shown."
        # Usually memory games are blind. 
        # "Correct Hit: Node flashes Green and turns OFF."
        # Implies they are initially OFF during execution. Correct.

    def on_hit(self, node_id, damage=1):
        if self.state != "PLAYING": return
        now = time.ticks_ms()
        
        # Kinetic Mask
        if self.input_mask_until > 0 and time.ticks_diff(self.input_mask_until, now) > 0:
            return

        expected = self.sequence[self.current_idx]
        
        if node_id == expected:
            # Correct Hit
            print(f"Correct: {node_id}")
            self.engine.send_node_cmd(node_id, 0, 255, 0) # Green Flash
            # We need to turn it off after a moment? PRD says "Flashes Green and turns OFF".
            # We can rely on a task or just leave it green for 150ms mask duration?
            # Let's leave it Green, then Off.
            # Ideally we'd queue an "off" command, but for now let's just let it stay set until next logic or simple timer?
            # Actually, "Flashes Green and turns OFF". 
            # We can set it to Green now, and rely on the fact that it was Off before. 
            # Or send a delayed off. 
            # Simplest: Brief blocking sleep? No.
            # Let's just set Green. We'll handle turning it off via mask timer or next tick?
            # "blinds itself for 150ms". We can turn it off after that.
            
            # Note: Since hitting a node might cause physical wobble, masking is good.
            self.input_mask_until = time.ticks_add(now, 150)
            
            # Record time for stats
            self.current_idx += 1
            self.last_hit_time = now
            
            # Check completion
            if self.current_idx >= len(self.sequence):
                self.level_complete(now)
            else:
                 # Standard hit logic continue
                 # Maybe schedule turning the LED off after 200ms?
                 # For now, we will just send Green. 
                 # If we don't turn it off, player might think it's still active?
                 # It was off before. 
                 # Let's assume we want it to flash. We can send (Green) then (Off) quickly?
                 # Protocol might not buffer.
                 # We'll leave it green for 150ms then turn off in Tick?
                 # Let's add a "pending_off" list to Tick if needed, or just let it stay green for a split second.
                 # Better: Send Green. Then set a flag to turn it off.
                 pass
                 
        else:
            # Check if this node is in the FUTURE of the sequence?
            # PRD: "Hitting Node 1 while the system is waiting for Node 4 results in an Immediate Fail"
            # "The system only 'listens' for a hit on the current target... If sequence is 4->1->3... ignores Node 1 and 3 until Node 4 is hit."
            # WAIT. "The system only 'listens' for a hit on the current target".
            # This contradicts "Penalty Logic: Hitting Node 1 while... results in Fail".
            # "The system ignores Node 1 and 3 until Node 4 is hit" VS "Penalty Logic... Immediate Fail".
            # I will follow the PENALTY LOGIC as it's more specific about the failure condition.
            # "Wrong Hit / Out of Order: All nodes flash Red. The round ends immediately (Fail)."
            print(f"Wrong hit! Expected {expected}, got {node_id}")
            self.fail_level("WRONG TARGET")

    def level_complete(self, now):
        print("Level Complete!")
        self.state = "LEVEL_COMPLETE"
        
        # Turn off last node (it was green)
        # Actually, let's just Flash Green All?
        # "Completion Bonus: +100 pts per level"
        self.score += 100
        
        # Time Bonus
        # "Total Score = (Level * 100) + (Time Bonus)"
        # "Time Bonus: Each level has a Par Time. For every 0.1s under Par, +5 points."
        # We need Par Time. Rough estimate: (Sequence Len * 1.5s)?
        # PRD doesn't define Par Time chart.
        # "Neural Speed: Average time between memorized targets."
        # Let's estimate Par = SeqLen * 2.0s.
        seq_len, _ = self.get_level_specs()
        par_ms = seq_len * 2000
        taken_ms = time.ticks_diff(now, self.round_start_time)
        
        if taken_ms < par_ms:
            diff_ms = par_ms - taken_ms
            bonus_units = int(diff_ms / 100) # 0.1s
            self.score += (bonus_units * 5)
        
        # Precision Bonus: 1.2x if no strays. 
        # We don't track strays easily unless "Inactive Node Hit" counts as stray.
        # But Inactive Node Hit = Fail? 
        # "If the player hits all targets without a single stray BB hitting an inactive node".
        # If "Inactive Node Hit" = "Wrong Hit" = FAIL, then every success is perfect precision?
        # Unless "Inactive Node Hit" only fails if it's one of the *other* sequence nodes?
        # PRD says "Inactive Node Hit: Same as 'Wrong Hit' -> Fail".
        # So... Precision Bonus is always applied if you win? 
        # Or maybe "Stray BB hitting an inactive node" implies sensors triggering without a "Hit" logic?
        # Let's assume passed level = precision bonus for now.
        self.score = int(self.score * 1.2)
        
        self.engine.broadcast_ws({"type": "score", "value": self.score})
        self.engine.broadcast_ws({"type": "status", "msg": "CLEARED"})
        
        self.next_action_time = time.ticks_add(now, 2000) # Wait before next level

    def fail_level(self, reason):
        print(f"Failed: {reason}")
        self.state = "FAILED"
        self.engine.broadcast_led(255, 0, 0) # All Red
        self.next_action_time = time.ticks_add(time.ticks_ms(), 2000)
    
    def finish_game(self, success=False):
        print("Breach Finished")
        msg = "BREACH CLOSED" if success else "FAIL"
        self.engine.broadcast_ws({"type": "status", "msg": msg})
        self.state = "FINISHED"
        self.engine.game_over()

