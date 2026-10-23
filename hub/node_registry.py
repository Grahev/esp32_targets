import time
import binascii

from storage import load_json, save_json

try:
    ticks_diff = time.ticks_diff
except AttributeError:  # CPython (tests)
    def ticks_diff(a, b):
        return a - b

OFFLINE_MS = 15000  # 3 missed heartbeats (nodes announce every 5 s)
DUP_WINDOW_MS = 2000


def mac_key(mac):
    return binascii.hexlify(mac).decode()


class NodeRegistry:
    """Which nodes exist (persisted) and which are online (this session).

    Identity is the sender's MAC. The first time a MAC is seen it gets the
    ID the node claims (from its config.json) if that ID is free, otherwise
    the lowest free ID. The mapping is saved to nodes.json, so IDs stay the
    same across hub reboots. To renumber nodes, edit nodes.json on the hub.
    """

    def __init__(self, path='nodes.json', offline_ms=OFFLINE_MS):
        self.path = path
        self.offline_ms = offline_ms
        self.ids = load_json(path, {})  # mac hex -> node id
        self.macs = {}       # node id -> mac bytes
        self.last_seen = {}  # node id -> ticks_ms, online nodes only
        self.last_seq = {}   # mac -> (seq, ticks_ms)
        self.unreachable = set()  # online nodes that just failed to ACK a unicast

    def node_id_for(self, mac, claimed=0):
        key = mac_key(mac)
        nid = self.ids.get(key)
        if nid is None:
            used = set(self.ids.values())
            if claimed and claimed not in used:
                nid = claimed
            else:
                nid = 1
                while nid in used:
                    nid += 1
            self.ids[key] = nid
            print(f"New node {key} -> ID {nid}")
            try:
                save_json(self.path, self.ids)
            except OSError as ex:
                print(f"Could not save {self.path}: {ex}")
        return nid

    def is_duplicate(self, mac, seq, now):
        """True if this (mac, seq) was already accepted moments ago (a retry)."""
        if seq is None:
            return False
        prev = self.last_seq.get(mac)
        self.last_seq[mac] = (seq, now)
        return prev is not None and prev[0] == seq and ticks_diff(now, prev[1]) < DUP_WINDOW_MS

    def seen(self, nid, mac, now):
        """Record a packet from a node. Returns True if it just came online."""
        joined = nid not in self.last_seen
        self.last_seen[nid] = now
        self.unreachable.discard(nid)
        self.macs[nid] = mac
        return joined

    def expire(self, now):
        """Mark nodes silent for longer than offline_ms as offline; return their IDs."""
        gone = [nid for nid, t in self.last_seen.items()
                if ticks_diff(now, t) > self.offline_ms or nid in self.unreachable]
        for nid in gone:
            del self.last_seen[nid]
        self.unreachable.clear()
        return gone

    def mark_unreachable(self, nid):
        """A unicast got no ACK (the radio already retried): drop the node on the
        next expire() instead of waiting for 3 missed heartbeats."""
        if nid in self.last_seen:
            self.unreachable.add(nid)

    def online(self):
        return sorted(self.last_seen)

    def is_online(self, nid):
        return nid in self.last_seen
