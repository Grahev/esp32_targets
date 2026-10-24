import network
import espnow
import struct

# Configuration
WIFI_CHANNEL = 1

# --- Node -> Hub ---
# v2: <ver:B><type:B><node_id:H><seq:H><batt_v:f><batt_pct:B><flags:B>
# Explicit little-endian, 12 bytes. node_id is the ID the node *claims*
# (0 = none yet); the hub decides the real ID from the sender's MAC.
# seq increases per message so the hub can drop retried duplicates.
PROTO_VERSION = 2
MSG_FORMAT = '<BBHHfBB'
MSG_SIZE = struct.calcsize(MSG_FORMAT)
# v1 (nodes not yet upgraded): native 'ifiBiB', 21 bytes
# <ID:int><BATT_V:float><BATT_P:int><HIT:uchar><MSG_TYPE:int><CHARGING:uchar>
MSG_V1_FORMAT = 'ifiBiB'
MSG_V1_SIZE = struct.calcsize(MSG_V1_FORMAT)

FLAG_HIT = 1
FLAG_CHARGING = 2

MSG_TYPE_HIT = 0
MSG_TYPE_ANNOUNCE = 1  # also the periodic heartbeat

# --- Hub -> Node ---
# <CMD_ID:int><A:uchar><B:uchar><C:uchar>, 7 bytes (unchanged from v1)
# 1=Set LED (r, g, b), 2=Set Mode (mode, 0, 0), 3=Set ID (id, 0, 0)
CMD_FORMAT = 'iBBB'
CMD_SIZE = struct.calcsize(CMD_FORMAT)
CMD_SET_LED = 1
CMD_SET_MODE = 2
CMD_SET_ID = 3

BROADCAST = b'\xff' * 6


def init_espnow(mode=network.AP_IF):
    """
    Initialize ESP-NOW.
    :param mode: network.STA_IF (Node) or network.AP_IF (Hub)
    :return: espnow object, wlan object
    """
    wlan = network.WLAN(mode)
    wlan.active(True)
    wlan.config(channel=WIFI_CHANNEL)

    # Initialize ESP-NOW
    e = espnow.ESPNow()
    e.active(True)

    return e, wlan


def pack_message(node_id, seq, battery_voltage, battery_percent, msg_type, hit=False, charging=False):
    flags = (FLAG_HIT if hit else 0) | (FLAG_CHARGING if charging else 0)
    return struct.pack(MSG_FORMAT, PROTO_VERSION, msg_type, node_id, seq & 0xFFFF,
                       battery_voltage, battery_percent, flags)


def unpack_message(data):
    """Return (version, msg_type, node_id, seq, batt_v, batt_pct, hit, charging) or None.

    seq is None for v1 packets (they have no sequence number).
    """
    try:
        if len(data) == MSG_SIZE and data[0] == PROTO_VERSION:
            ver, msg_type, node_id, seq, batt, pct, flags = struct.unpack(MSG_FORMAT, data)
            return ver, msg_type, node_id, seq, batt, pct, bool(flags & FLAG_HIT), bool(flags & FLAG_CHARGING)
        if len(data) == MSG_V1_SIZE:
            node_id, batt, pct, hit, msg_type, chg = struct.unpack(MSG_V1_FORMAT, data)
            return 1, msg_type, node_id, None, batt, pct, bool(hit), bool(chg)
    except Exception:
        pass
    return None


def pack_command(cmd_id, r, g, b):
    return struct.pack(CMD_FORMAT, cmd_id, r, g, b)


def unpack_command(data):
    if len(data) != CMD_SIZE:
        return None
    try:
        return struct.unpack(CMD_FORMAT, data)
    except Exception:
        return None
