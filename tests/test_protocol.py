import sys
import os
import struct
import unittest
from unittest.mock import MagicMock

# Add root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock MicroPython modules
sys.modules['network'] = MagicMock()
sys.modules['espnow'] = MagicMock()

from common.espnow_utils import pack_message, unpack_message, MSG_TYPE_HIT, MSG_TYPE_ANNOUNCE

class TestProtocol(unittest.TestCase):
    def test_pack_unpack_hit(self):
        # ID=1, V=3.3, Hit=True, Type=Default(Hit)
        msg = pack_message(1, 3.3, True)
        unpacked = unpack_message(msg)
        
        self.assertIsNotNone(unpacked)
        self.assertEqual(unpacked[0], 1)
        self.assertAlmostEqual(unpacked[1], 3.3, places=2)
        self.assertEqual(unpacked[2], 1)
        self.assertEqual(unpacked[3], MSG_TYPE_HIT)

    def test_pack_unpack_announce(self):
        # ID=2, V=4.0, Hit=False, Type=Announce
        msg = pack_message(2, 4.0, False, msg_type=MSG_TYPE_ANNOUNCE)
        unpacked = unpack_message(msg)
        
        self.assertIsNotNone(unpacked)
        self.assertEqual(unpacked[0], 2)
        self.assertAlmostEqual(unpacked[1], 4.0, places=2)
        self.assertEqual(unpacked[2], 0)
        self.assertEqual(unpacked[3], MSG_TYPE_ANNOUNCE)

if __name__ == '__main__':
    unittest.main()
