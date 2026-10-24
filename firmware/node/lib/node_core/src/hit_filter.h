// Turns raw SW-420 edges into hits: a hit needs `edges` rising edges within
// `window_ms`, and is followed by a `debounce_ms` lockout. SW-420 modules vary
// a lot, so all three are set per node from the app (sensor test screen).
#pragma once

#include <stdint.h>

struct HitResult {
  bool hit;
  uint32_t at_ms;  // time of the first edge of the burst
  uint8_t edges;
};

class HitFilter {
 public:
  void configure(uint16_t debounce_ms, uint8_t edges, uint16_t window_ms);
  // Feed edges in time order (timestamps captured in the IRQ handler)
  HitResult onEdge(uint32_t ms);
  // Drops an unfinished burst once its window has passed
  void poll(uint32_t now);

 private:
  uint16_t debounce_ms_ = 300;
  uint8_t need_ = 1;
  uint16_t window_ms_ = 30;
  bool locked_ = false;
  uint32_t lock_from_ = 0;
  uint8_t count_ = 0;
  uint32_t first_ = 0;
};
