// Game modes. A mode is a state machine driven by tick() every 10 ms and by
// onHit(); it lights targets through GameHost and never blocks. Each mode
// publishes a settings schema, which the app turns into its setup form.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include <string>
#include <vector>

#include "protocol.h"

struct LedCmd {
  proto::Effect effect;
  uint8_t r, g, b;
  uint16_t p1, p2;
};

namespace led {
inline LedCmd off() { return LedCmd{proto::Effect::Off, 0, 0, 0, 0, 0}; }
inline LedCmd solid(uint8_t r, uint8_t g, uint8_t b) { return LedCmd{proto::Effect::Solid, r, g, b, 0, 0}; }
inline LedCmd flash(uint8_t r, uint8_t g, uint8_t b, uint16_t ms) {
  return LedCmd{proto::Effect::Flash, r, g, b, ms, 0};
}
inline LedCmd blink(uint8_t r, uint8_t g, uint8_t b, uint16_t period, uint16_t count) {
  return LedCmd{proto::Effect::Blink, r, g, b, period, count};
}
inline LedCmd ramp(uint8_t r, uint8_t g, uint8_t b, uint16_t ms, uint8_t from) {
  return LedCmd{proto::Effect::Ramp, r, g, b, ms, from};
}
inline LedCmd red() { return solid(255, 0, 0); }
inline LedCmd green() { return solid(0, 255, 0); }
}  // namespace led

class GameHost {
 public:
  virtual ~GameHost() {}
  virtual uint32_t now() const = 0;
  virtual const std::vector<uint8_t>& slots() const = 0;  // online targets, ascending
  virtual void led(uint8_t slot, const LedCmd& cmd) = 0;  // a new effect (restarts it)
  virtual void ledAll(const LedCmd& cmd) = 0;
  virtual void hudChanged() = 0;  // re-send hud() to the app
  // A line in the app's hit feed: points (0 = none), reaction time (-1 = none)
  virtual void feed(uint8_t slot, int points, int rt_ms, const char* note) = 0;
  virtual uint32_t random(uint32_t n) = 0;  // 0..n-1
  virtual void finish(bool save) = 0;      // game over (handled after the current call)
};

class GameMode {
 public:
  explicit GameMode(GameHost& host) : host_(host) {}
  virtual ~GameMode() {}
  virtual bool configure(JsonObjectConst cfg, std::string& err) = 0;
  virtual void start() = 0;
  virtual void tick() = 0;
  // node_rt_ms: reaction time measured on the node, proto::RT_NONE if unknown
  virtual void onHit(uint8_t slot, uint16_t node_rt_ms) = 0;
  virtual void onNodeLost(uint8_t slot) { (void)slot; }
  virtual void onNodeFound(uint8_t slot) { (void)slot; }
  virtual void stop() { host_.ledAll(led::off()); }
  // Live state for the app: score, time_left, combo, level, status...
  virtual void hud(JsonObject out) const = 0;
  // Leaderboard entry fields (the hub adds score, player, date, label)
  virtual void result(JsonObject out) const = 0;
  virtual long score() const = 0;
  virtual bool saveable() const { return true; }
  // The target the player must hit next, when the mode knows it but the LEDs
  // don't show it (The Breach). Used by simulated targets and tests; 0 = none.
  virtual uint8_t nextExpected() const { return 0; }
  virtual std::string label() const = 0;  // "Normal · 2 min": groups the leaderboard

 protected:
  GameHost& host_;
};

// The common start: targets blink yellow three times, flash green, then play
class Countdown {
 public:
  static constexpr uint32_t BLINKS_MS = 2400;
  static constexpr uint32_t GO_MS = 800;
  void begin(GameHost& h);
  // True once, when the countdown is over
  bool tick(GameHost& h);
  bool running() const { return phase_ != 0; }
  int secondsLeft(uint32_t now) const;

 private:
  int phase_ = 0;  // 0 idle, 1 blinking, 2 green
  uint32_t at_ = 0;
};

struct ModeInfo {
  const char* id;
  const char* schema;  // JSON, served by /api/v1/modes
  uint8_t min_nodes;
  GameMode* (*create)(GameHost&);
};

const std::vector<ModeInfo>& gameModes();
const ModeInfo* findMode(const std::string& id);

// Settings helpers for configure()
int cfgInt(JsonObjectConst cfg, const char* key, int def, int lo, int hi, std::string& err);
bool cfgEnum(JsonObjectConst cfg, const char* key, const char* def, const char* const* options, int n,
             std::string& out, std::string& err);
