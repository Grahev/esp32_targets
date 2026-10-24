// Paired targets (/nodes.json) and their live state. A target is identified by
// its MAC and shown by its slot number 1..max_nodes, which the user can change.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include <string>
#include <vector>

#include "ports.h"
#include "protocol.h"

struct TargetConfig {  // mirrored on the node (protocol Key)
  uint16_t debounce_ms = 300;
  uint8_t glitch_edges = 1;
  uint16_t glitch_window_ms = 30;
  uint16_t batt_scale_uv = 4102;
  bool hit_flash = true;
  uint8_t led_pin = 0;
};

struct NodeRec {
  Mac mac;
  uint8_t slot = 0;
  std::string name;
  uint8_t color = 0;  // tag colour index in the app
  TargetConfig cfg;
  bool virt = false;  // simulated target (never saved)

  // live
  bool online = false;
  uint32_t last_seen = 0;
  uint16_t batt_mv = 0;
  uint8_t batt_pct = proto::BATT_UNKNOWN;
  uint8_t flags = 0;
  int8_t rssi = 0;
  uint8_t fw[3] = {0, 0, 0};
  uint8_t caps = 0;
  uint8_t mode = 0;  // as reported by the node
  uint32_t uptime_s = 0;
  bool has_seq = false;
  uint16_t last_seq = 0;
  uint32_t last_seq_at = 0;
  uint8_t send_fails = 0;
  uint32_t hits = 0;
  // LED as last commanded (the app mirrors it on the HUD tiles)
  proto::Led led{};
  uint32_t led_sent_at = 0;

  void toJson(JsonObject o) const;  // for the app
};

struct PendingNode {  // said hello, not added yet
  Mac mac;
  uint32_t first_seen = 0;
  uint32_t last_seen = 0;
  uint8_t fw[3] = {0, 0, 0};
  uint16_t batt_mv = 0;
  uint8_t batt_pct = proto::BATT_UNKNOWN;
  void toJson(JsonObject o, uint32_t now) const;
};

class NodeRegistry {
 public:
  std::vector<NodeRec> nodes;  // sorted by slot
  std::vector<PendingNode> pending;

  NodeRec* byMac(const Mac& m);
  NodeRec* bySlot(uint8_t slot);
  uint8_t freeSlot(uint8_t max_nodes) const;  // 0 = full
  NodeRec& add(const Mac& m, uint8_t slot, bool virt);
  void remove(const Mac& m);
  // Moves a node to `slot`, swapping with the node there (if any). Returns that node.
  NodeRec* moveTo(NodeRec& n, uint8_t slot);
  void sort();
  std::vector<uint8_t> onlineSlots() const;
  size_t realCount() const;

  PendingNode& touchPending(const Mac& m, uint32_t now);
  void dropPending(const Mac& m);
  void expirePending(uint32_t now, uint32_t max_age_ms);

  bool load(Fs& fs);
  bool save(Fs& fs) const;
};
