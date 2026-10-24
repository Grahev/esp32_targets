# Base class for game modes. Each mode lives in its own module
# (mode_time_attack.py, mode_breach.py) so the hub only keeps the mode being
# played in RAM (REVIEW #36).

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
