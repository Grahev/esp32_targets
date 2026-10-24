// Simulated targets that run inside the hub, for testing with fewer real
// targets than a game needs. Each one runs the real node firmware logic
// (node_core NodeLogic), so pairing, effects and reaction times behave exactly
// like a real target. MACs are 02:00:00:00:00:0N. An optional auto-shooter
// hits red targets (and The Breach's next target) after a human-like delay.
#pragma once

#include <stdint.h>

#include <memory>
#include <vector>

#include "node_logic.h"
#include "ports.h"

struct OutFrame {
  Mac from;
  uint8_t len;
  uint8_t data[proto::MAX_FRAME];
};

class VirtualNodes {
 public:
  void resize(uint8_t count, uint32_t now);
  uint8_t count() const { return static_cast<uint8_t>(nodes_.size()); }
  // hub -> virtual node (unicast to one, or broadcast to all when mac is null)
  void deliver(const Mac* mac, const uint8_t* data, size_t len);
  // expected: the slot the game wants hit next (0 = none)
  void tick(uint32_t now, bool autoshoot, uint8_t expected);
  void hit(const Mac& mac, uint32_t now);
  std::vector<OutFrame>& outbox() { return outbox_; }

 private:
  struct VNode;
  struct VIo : NodeIo {
    VirtualNodes* owner = nullptr;
    Mac mac;
    bool done_pending = false;
    bool send(const uint8_t* to, const uint8_t* data, size_t len) override;
    void setChannel(uint8_t) override {}
    void saveConfig(const NodeConfig&) override {}
    void reboot() override {}
    bool otaBegin(uint32_t, const uint8_t*) override { return false; }
    bool otaWrite(const uint8_t*, size_t) override { return false; }
    bool otaEnd() override { return false; }
    void otaAbort() override {}
    void log(const char*) override {}
  };
  struct VNode {
    Mac mac;
    NodeConfig cfg;
    VIo io;
    std::unique_ptr<NodeLogic> logic;
    uint32_t shoot_at = 0;
    bool shot_scheduled = false;
    uint32_t cooldown_until = 0;
    std::vector<std::vector<uint8_t>> inbox;
  };

  uint32_t rnd(uint32_t n);

  std::vector<std::unique_ptr<VNode>> nodes_;
  std::vector<OutFrame> outbox_;
  uint32_t rng_ = 0x9e3779b9;
};
