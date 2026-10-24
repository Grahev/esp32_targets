import struct
import unittest

import hub_env  # noqa: F401  (stubs network/espnow so common/ imports on CPython)
from common.espnow_utils import (pack_message, unpack_message, pack_command, unpack_command,
                                 MSG_SIZE, MSG_V1_SIZE, CMD_SIZE, MSG_TYPE_HIT, MSG_TYPE_ANNOUNCE,
                                 CMD_SET_ID)


class TestProtocol(unittest.TestCase):
    def test_sizes_match_what_the_boards_use(self):
        # Measured on the ESP32 hub and ESP8266 node: v1 = 21, command = 7
        self.assertEqual((MSG_SIZE, MSG_V1_SIZE, CMD_SIZE), (12, 21, 7))

    def test_v2_hit_round_trip(self):
        msg = pack_message(4, 1234, 3.75, 62, MSG_TYPE_HIT, hit=True, charging=True)
        ver, typ, nid, seq, batt, pct, hit, chg = unpack_message(msg)
        self.assertEqual((ver, typ, nid, seq, pct, hit, chg), (2, MSG_TYPE_HIT, 4, 1234, 62, True, True))
        self.assertAlmostEqual(batt, 3.75, places=2)

    def test_seq_wraps_at_16_bits(self):
        self.assertEqual(unpack_message(pack_message(0, 65536 + 5, 4.0, 90, MSG_TYPE_ANNOUNCE))[3], 5)

    def test_v1_packet_from_old_node(self):
        v1 = struct.pack('ifiBiB', 2, 4.1, 95, 1, MSG_TYPE_HIT, 0)
        self.assertEqual(unpack_message(v1)[:4], (1, MSG_TYPE_HIT, 2, None))

    def test_garbage_is_rejected(self):
        for data in (b'', b'x' * 7, b'\x09' + b'\x00' * 11, b'x' * 30):
            self.assertIsNone(unpack_message(data))

    def test_command_round_trip_and_length_check(self):
        self.assertEqual(unpack_command(pack_command(CMD_SET_ID, 3, 0, 0)), (CMD_SET_ID, 3, 0, 0))
        self.assertIsNone(unpack_command(pack_message(1, 1, 4.0, 90, MSG_TYPE_ANNOUNCE)))


if __name__ == '__main__':
    unittest.main()
