// Time Attack+ (ported from v1 mode_time_attack.py, same rules and tables).
// Red = live target. A hit scores 10 / 5 / 2 by reaction time (< 750 ms,
// <= 1400 ms, slower), x1.5 once the combo passes 3. A hit on a dark target
// costs 15 and freezes every target orange for 1 s. The minimum number of lit
// targets rises every 30 s, by difficulty.
#include <algorithm>

#include "../game.h"
#include "difficulty.h"
#include "slot_stats.h"
#include "spawner.h"

namespace {

const char SCHEMA[] = R"json({"id":"time_attack","name":"Time Attack+","min_nodes":1,
"tagline":"Hit the red targets as fast as you can",
"rules":["Red target = shoot it. Faster hits score more: under 0.75 s = 10, under 1.4 s = 5, slower = 2.",
"Keep a streak: from the 4th hit in a row points are x1.5. 4 s without a hit ends the streak.",
"Hitting a dark target costs 15 points and freezes all targets orange for 1 s.",
"More targets light up at once as time goes on."],
"settings":[{"key":"duration","label":"Duration","type":"int","min":1,"max":10,"def":1,"unit":"min"},
{"key":"difficulty","label":"Difficulty","type":"enum","options":["Easy","Normal","Hard","Extreme"],"def":"Normal"},
{"key":"penalties","label":"Penalties for dark targets","type":"bool","def":true}],
"presets":{"Warm-up":{"duration":1,"difficulty":"Easy"},"Standard":{"duration":2,"difficulty":"Normal"},"Pro":{"duration":3,"difficulty":"Hard"}}})json";

constexpr int HIT_POINTS_FAST = 10, HIT_POINTS_OK = 5, HIT_POINTS_SLOW = 2;
constexpr int STRAY_PENALTY = -15;
constexpr uint32_t FREEZE_MS = 1000;
constexpr uint32_t COMBO_TIMEOUT_MS = 4000;
constexpr uint32_t INPUT_MASK_MS = 150;  // a hit target can shake its neighbours

class TimeAttack : public GameMode {
 public:
  using GameMode::GameMode;

  bool configure(JsonObjectConst cfg, std::string& err) override {
    duration_min_ = cfgInt(cfg, "duration", 1, 1, 10, err);
    if (!err.empty()) return false;
    if (!cfgEnum(cfg, "difficulty", "Normal", difficulty::NAMES, difficulty::COUNT, diff_, err)) return false;
    penalties_ = cfg["penalties"] | true;
    return true;
  }

  void start() override {
    state_ = State::Countdown;
    spawner_.reset();
    countdown_.begin(host_);
    host_.hudChanged();
  }

  void tick() override {
    const uint32_t now = host_.now();
    if (state_ == State::Countdown) {
      if (countdown_.tick(host_)) startPlay(now);
      int s = countdown_.secondsLeft(now);
      if (s != last_second_) {
        last_second_ = s;
        host_.hudChanged();
      }
      return;
    }
    if (state_ != State::Playing) return;

    int32_t remaining = static_cast<int32_t>(end_ - now);
    if (remaining <= 0) {
      state_ = State::Done;
      host_.finish(true);
      return;
    }
    int second = (remaining + 999) / 1000;
    if (second != last_second_) {
      last_second_ = second;
      host_.hudChanged();
    }
    stage_ = std::min<int>(5, (now - start_) / 30000);

    if (freeze_end_) {
      if (static_cast<int32_t>(freeze_end_ - now) > 0) return;  // timer runs, nothing spawns
      freeze_end_ = 0;
      host_.ledAll(led::off());
      for (auto& a : active_) {
        host_.led(a.slot, led::red());
        a.relit = true;  // the node's own reaction time restarted: use the hub's
      }
    }

    schedule(now);

    if (combo_ && now - last_hit_ > COMBO_TIMEOUT_MS) {
      combo_ = 0;
      host_.hudChanged();
    }
  }

  void onHit(uint8_t slot, uint16_t node_rt) override {
    if (state_ != State::Playing) return;
    const uint32_t now = host_.now();
    if (mask_end_ && static_cast<int32_t>(mask_end_ - now) > 0) return;

    auto it = std::find_if(active_.begin(), active_.end(), [&](const Active& a) { return a.slot == slot; });
    if (it != active_.end()) {
      uint32_t rt = (node_rt != proto::RT_NONE && !it->relit) ? node_rt : now - it->at;
      active_.erase(it);
      host_.led(slot, led::off());
      mask_end_ = now + INPUT_MASK_MS;
      last_hit_ = now;

      int points = rt < 750 ? HIT_POINTS_FAST : rt <= 1400 ? HIT_POINTS_OK : HIT_POINTS_SLOW;
      combo_++;
      max_combo_ = std::max(max_combo_, combo_);
      if (combo_ > 3) points = points * 3 / 2;
      score_ += points;
      stats_.add(slot, rt);
      host_.feed(slot, points, static_cast<int>(rt), combo_ > 3 ? "x1.5" : "");
      host_.hudChanged();

      next_spawn_ = now + difficulty::spawnDelayMs(stage_);
      spawner_.hit(slot);
      return;
    }
    if (!penalties_) {
      host_.feed(slot, 0, -1, "dark target");
      return;
    }
    score_ += STRAY_PENALTY;
    misses_++;
    combo_ = 0;
    freeze_end_ = now + FREEZE_MS;
    host_.ledAll(led::solid(255, 140, 0));
    host_.feed(slot, STRAY_PENALTY, -1, "dark target: freeze");
    host_.hudChanged();
  }

  void onNodeLost(uint8_t slot) override {
    // A dead target can't be hit: forget it so another one lights
    active_.erase(std::remove_if(active_.begin(), active_.end(), [&](const Active& a) { return a.slot == slot; }),
                  active_.end());
  }

  void hud(JsonObject o) const override {
    o["status"] = state_ == State::Countdown ? "GET READY" : state_ == State::Playing ? (freeze_end_ ? "FREEZE" : "GO") : "OVER";
    o["score"] = score_;
    o["combo"] = combo_;
    o["hits"] = stats_.total_hits;
    o["misses"] = misses_;
    if (state_ == State::Countdown) o["countdown"] = countdown_.secondsLeft(host_.now());
    o["time_left"] = state_ == State::Playing ? last_second_ : (state_ == State::Countdown ? duration_min_ * 60 : 0);
    o["time_total"] = duration_min_ * 60;
  }

  void result(JsonObject o) const override {
    o["hits"] = stats_.total_hits;
    o["misses"] = misses_;
    o["avg_rt"] = stats_.avg();
    o["best_rt"] = stats_.best_rt;
    o["max_combo"] = max_combo_;
    o["difficulty"] = diff_;
    o["duration_min"] = duration_min_;
    stats_.toJson(o["slots"].to<JsonArray>());
  }

  long score() const override { return score_; }
  bool saveable() const override { return stats_.total_hits > 0 || score_ != 0; }
  std::string label() const override { return diff_ + " · " + std::to_string(duration_min_) + " min"; }

 private:
  enum class State { Countdown, Playing, Done };
  struct Active {
    uint8_t slot;
    uint32_t at;
    bool relit;
  };

  void startPlay(uint32_t now) {
    state_ = State::Playing;
    start_ = now;
    end_ = now + duration_min_ * 60000UL;
    last_hit_ = now;
    next_spawn_ = now;
    last_second_ = -1;
    spawn(now);  // one target straight away
    host_.hudChanged();
  }

  void schedule(uint32_t now) {
    int min_active = difficulty::MIN_TARGETS[difficulty::index(diff_)][stage_];
    min_active = std::min<int>(min_active, host_.slots().size());
    int needed = min_active - static_cast<int>(active_.size());
    if (needed > 0 && static_cast<int32_t>(now - next_spawn_) >= 0) {
      for (int i = 0; i < needed; i++) spawn(now);
    }
  }

  void spawn(uint32_t now) {
    std::vector<uint8_t> busy;
    for (auto& a : active_) busy.push_back(a.slot);
    uint8_t s = spawner_.pick(host_, busy);
    if (!s) return;
    active_.push_back(Active{s, now, false});
    host_.led(s, led::red());
  }

  int duration_min_ = 1;
  std::string diff_ = "Normal";
  bool penalties_ = true;

  State state_ = State::Countdown;
  Countdown countdown_;
  Spawner spawner_;
  std::vector<Active> active_;
  SlotStats stats_;
  long score_ = 0;
  int combo_ = 0, max_combo_ = 0, misses_ = 0, stage_ = 0, last_second_ = -1;
  uint32_t start_ = 0, end_ = 0, last_hit_ = 0, next_spawn_ = 0, freeze_end_ = 0, mask_end_ = 0;
};

GameMode* create(GameHost& h) { return new TimeAttack(h); }

}  // namespace

extern const ModeInfo MODE_TIME_ATTACK = {"time_attack", SCHEMA, 1, create};
