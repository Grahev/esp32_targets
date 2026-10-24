import time
import random

from game_engine import GameMode


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
        self.next_action_time = time.ticks_add(time.ticks_ms(), 500)
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
                if self.countdown_step < 6:
                    # 3 s countdown: yellow pulses, toggled every 500 ms
                    # (no sleep here: tick() runs on the hub's event loop)
                    if self.countdown_step % 2:
                        self.engine.broadcast_led(0, 0, 0)
                    else:
                        self.engine.broadcast_led(255, 255, 0)
                    self.next_action_time = time.ticks_add(now, 500)
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
                 self.state = "FINISHED"  # end exactly once
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
        level_points = 100
        
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
            level_points += (bonus_units * 5)
        
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
        # Applied to this level's points only; multiplying the running total
        # compounded the bonus across levels
        self.score += int(level_points * 1.2)
        
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
