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

class TimeAttack(GameMode):
    def __init__(self, engine):
        super().__init__(engine)
        self.name = "Time Attack"
        self.targets_left = 3
        self.start_time = 0

    def start(self):
        self.targets_left = 3
        self.start_time = time.ticks_ms()
        self.engine.broadcast_led(255, 0, 0) # All Red
        print("Time Attack Started")

    def on_hit(self, node_id, damage=1):
        if self.targets_left > 0:
            self.targets_left -= 1
            print(f"Hit! {self.targets_left} left")
            # Turn off that target (logic needed to address specific node)
            self.engine.send_node_cmd(node_id, 0, 0, 0) 
            
            if self.targets_left == 0:
                duration = time.ticks_diff(time.ticks_ms(), self.start_time) / 1000.0
                print(f"Finished in {duration}s")
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
