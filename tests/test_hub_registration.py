import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock MicroPython modules
sys.modules['network'] = MagicMock()
sys.modules['espnow'] = MagicMock()
sys.modules['machine'] = MagicMock()
sys.modules['time'] = MagicMock()
sys.modules['uasyncio'] = MagicMock()
sys.modules['ujson'] = MagicMock()

# Mock Microdot/Libs that might not exist locally or import mpy
sys.modules['microdot_asyncio'] = MagicMock()
sys.modules['microdot_websocket'] = MagicMock()
sys.modules['game_engine'] = MagicMock()

# Mock common to avoid import issues inside Hub if any (though we used it above)
# We need real common for constants if possible, but let's see.
# Actually, hub imports common.espnow_utils. if we mocked espnow, that import works.

from hub.main import HUB_SYSTEM

class TestHubRegistration(unittest.TestCase):
    def setUp(self):
        self.hub = HUB_SYSTEM()
        self.hub.esp = MagicMock()
        self.hub.broadcast_ws = MagicMock()
    
    def test_initial_state(self):
        self.assertEqual(self.hub.available_nodes, [])
    
    def test_register_single_node(self):
        self.hub.register_node(1, b'\x11'*6)
        self.assertEqual(self.hub.available_nodes, [1])
        self.hub.esp.add_peer.assert_called_with(b'\x11'*6)
        
    def test_register_multiple_nodes(self):
        self.hub.register_node(1, b'\x11'*6)
        self.hub.register_node(2, b'\x22'*6)
        
        self.assertEqual(len(self.hub.available_nodes), 2)
        self.assertIn(1, self.hub.available_nodes)
        self.assertIn(2, self.hub.available_nodes)
        
    def test_duplicate_registration_ignored(self):
        self.hub.register_node(1, b'\x11'*6)
        self.hub.register_node(1, b'\x11'*6)
        self.assertEqual(self.hub.available_nodes, [1])

    def test_re_registration_updates_mac(self):
        self.hub.register_node(1, b'\x11'*6)
        self.assertEqual(self.hub.node_macs[1], b'\x11'*6)
        
        # Node restarts with new MAC (unlikely but possible) or valid update
        self.hub.register_node(1, b'\x33'*6)
        self.assertEqual(self.hub.node_macs[1], b'\x33'*6)
        self.hub.esp.add_peer.assert_called_with(b'\x33'*6)

if __name__ == '__main__':
    unittest.main()
