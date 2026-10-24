// Hits and reaction times per target, saved with each game for the
// "slowest side" statistics in the app.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include "protocol.h"

struct SlotStats {
  uint16_t hits[proto::MAX_NODES_HARD + 1] = {0};
  uint32_t rt_sum[proto::MAX_NODES_HARD + 1] = {0};
  uint32_t total_rt = 0;
  uint32_t total_hits = 0;
  uint32_t best_rt = 0;

  void add(uint8_t slot, uint32_t rt) {
    if (slot > proto::MAX_NODES_HARD) return;
    hits[slot]++;
    rt_sum[slot] += rt;
    total_rt += rt;
    total_hits++;
    if (!best_rt || rt < best_rt) best_rt = rt;
  }
  uint32_t avg() const { return total_hits ? total_rt / total_hits : 0; }
  // [[slot, hits, avg_rt], ...]
  void toJson(JsonArray out) const {
    for (int s = 1; s <= proto::MAX_NODES_HARD; s++) {
      if (!hits[s]) continue;
      JsonArray a = out.add<JsonArray>();
      a.add(s);
      a.add(hits[s]);
      a.add(rt_sum[s] / hits[s]);
    }
  }
};
