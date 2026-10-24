#include "game.h"

void Countdown::begin(GameHost& h) {
  phase_ = 1;
  at_ = h.now();
  h.ledAll(led::blink(255, 200, 0, BLINKS_MS / 3, 3));
}

bool Countdown::tick(GameHost& h) {
  uint32_t t = h.now() - at_;
  if (phase_ == 1 && t >= BLINKS_MS) {
    phase_ = 2;
    h.ledAll(led::flash(0, 255, 0, GO_MS));
    return false;
  }
  if (phase_ == 2 && t >= BLINKS_MS + GO_MS) {
    phase_ = 0;
    return true;
  }
  return false;
}

int Countdown::secondsLeft(uint32_t now) const {
  if (!phase_) return 0;
  uint32_t t = now - at_;
  uint32_t total = BLINKS_MS + GO_MS;
  return t >= total ? 0 : static_cast<int>((total - t + 999) / 1000);
}

int cfgInt(JsonObjectConst cfg, const char* key, int def, int lo, int hi, std::string& err) {
  if (cfg[key].isNull()) return def;
  if (!cfg[key].is<int>()) {
    err = std::string(key) + " must be a number";
    return def;
  }
  int v = cfg[key].as<int>();
  if (v < lo || v > hi) {
    err = std::string(key) + " must be " + std::to_string(lo) + "-" + std::to_string(hi);
    return def;
  }
  return v;
}

bool cfgEnum(JsonObjectConst cfg, const char* key, const char* def, const char* const* options, int n,
             std::string& out, std::string& err) {
  out = cfg[key] | def;
  for (int i = 0; i < n; i++)
    if (out == options[i]) return true;
  err = std::string("Unknown ") + key + " " + out;
  return false;
}

// Registry: see modes/*.cpp
extern const ModeInfo MODE_FREE_PRACTICE;
extern const ModeInfo MODE_TIME_ATTACK;
extern const ModeInfo MODE_BREACH;
extern const ModeInfo MODE_SHOOT_NO_SHOOT;

const std::vector<ModeInfo>& gameModes() {
  static const std::vector<ModeInfo> modes = {MODE_TIME_ATTACK, MODE_BREACH, MODE_SHOOT_NO_SHOOT,
                                              MODE_FREE_PRACTICE};
  return modes;
}

const ModeInfo* findMode(const std::string& id) {
  for (auto& m : gameModes())
    if (id == m.id) return &m;
  return nullptr;
}
