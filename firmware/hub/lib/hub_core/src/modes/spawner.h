// Picks the next target to light, as in v1 Time Attack+: never the target that
// was just hit (unless it is the only one), and weighted towards the targets
// lit least often so far, so every target gets a fair share.
#pragma once

#include <stdint.h>

#include <vector>

#include "../game.h"

class Spawner {
 public:
  void reset() {
    for (auto& c : count_) c = 0;
    for (auto& k : known_) k = false;
    last_hit_ = 0;
  }
  void hit(uint8_t slot) { last_hit_ = slot; }
  // 0 if nothing can be lit now
  uint8_t pick(GameHost& h, const std::vector<uint8_t>& busy);

 private:
  uint32_t count_[proto::MAX_NODES_HARD + 1] = {0};
  bool known_[proto::MAX_NODES_HARD + 1] = {false};
  uint8_t last_hit_ = 0;
};
