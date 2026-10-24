// LED effects rendered on the node, so the hub sends one command per change
// instead of streaming colours (protocol.h Effect).
#pragma once

#include <stdint.h>

#include "protocol.h"

struct Rgb {
  uint8_t r, g, b;
  bool operator==(const Rgb& o) const { return r == o.r && g == o.g && b == o.b; }
  bool operator!=(const Rgb& o) const { return !(*this == o); }
  bool isOff() const { return !r && !g && !b; }
};

// level 0..255
Rgb scale(Rgb c, uint8_t level);

class EffectPlayer {
 public:
  // Applies a Led command. A command with the same non-zero effect_id as the
  // one showing is a re-send and doesn't restart the effect. Returns true if
  // the effect changed.
  bool apply(const proto::Led& cmd, uint32_t now);
  // Turns the LED off locally (after a hit) until the hub sends a new effect
  void clear(uint32_t now);
  Rgb render(uint32_t now) const;
  // True while the effect is showing (Blink with a count and Flash end by themselves)
  bool lit(uint32_t now) const;
  uint8_t id() const { return cmd_.effect_id; }
  // When the current effect lit up, for the reaction time
  uint32_t litAt() const { return lit_at_; }

 private:
  proto::Effect effect() const { return static_cast<proto::Effect>(cmd_.effect); }
  proto::Led cmd_{};
  uint32_t start_ = 0;
  uint32_t lit_at_ = 0;
  uint8_t consumed_id_ = 0;
};
