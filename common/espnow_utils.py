import network
import espnow
import struct

# Configuration
WIFI_CHANNEL = 1
ESPNOW_PMK = "AirsoftGemini2026"  # Primary Master Key (Optional, but good practice)

# Message Protocol
# Format: <ID:int><BATT_V:float><BATT_P:int><HIT:bool><MSG_TYPE:int><CHARGING:uchar>
# Struct format: 'ifiBiB' (i=int, f=float, i=int, B=uchar, i=int, B=uchar)
MSG_FORMAT = 'ifiBiB' 

MSG_TYPE_HIT = 0
MSG_TYPE_ANNOUNCE = 1

# Command Protocol (Hub -> Node)
# Format: <CMD_ID:int><R:int><G:int><B:int>
# CMD_ID: 1=Set LED
CMD_FORMAT = 'iBBB'

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

def pack_message(target_id, battery_voltage, battery_percent, hit_detected, msg_type=MSG_TYPE_HIT, charging=False):
    return struct.pack(MSG_FORMAT, target_id, battery_voltage, battery_percent, int(hit_detected), msg_type, int(charging))

def unpack_message(data):
    try:
        return struct.unpack(MSG_FORMAT, data)
    except Exception:
        return None

def pack_command(cmd_id, r, g, b):
    return struct.pack(CMD_FORMAT, cmd_id, r, g, b)

def unpack_command(data):
    try:
        return struct.unpack(CMD_FORMAT, data)
    except Exception:
        return None
