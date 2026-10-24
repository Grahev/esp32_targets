// Shoot / No-Shoot (new in v2): red = threat, shoot it before it goes dark;
// green = hostage, don't shoot. Builds on the Time Attack+ scheduler. On Hard
// and Extreme a lit target can switch colour once.
#include <algorithm>

#include "../game.h"
#include "difficulty.h"
#include "slot_stats.h"
#include "spawner.h"

namespace {

const char SCHEMA[] = R"json({"id":"shoot_no_shoot","name":"Shoot / No-Shoot","min_nodes":2,
"tagline":"Red = threat, green = hostage. Think before you shoot",
"rules":["Red target = threat: hit it before it goes dark. Faster = more points (10 / 5 / 2).",
"Green target = hostage: don't shoot it (-25). Letting it go dark gives +2.",
"A threat that goes dark unhit costs 5. Hitting a dark target costs 5.",
"On Hard and Extreme a target can switch colour while it is lit."],
"settings":[{"key":"duration","label":"Duration","type":"int","min":1,"max":10,"def":2,"unit":"min"},
{"key":"difficulty","label":"Difficulty","type":"enum","options":["Easy","Normal","Hard","Extreme"],"def":"Normal"}],
"presets":{"Intro":{"duration":1,"difficulty":"Easy"},"Standard":{"duration":2,"difficulty":"Normal"},"Pro":{"duration":3,"difficulty":"Hard"}}})json";

struct Tuning {
  uint8_t hostage_pct;
  uint16_t threat_window_ms;
  uint16_t hostage_window_ms;
  uint8_t switch_pct;
};
const Tuning TUNING[difficulty::COUNT] = {
    {20, 3000, 2000, 0}, {30, 2500, 2000, 0}, {40, 2000, 1800, 15}, {50, 1500, 1500, 25}};

constexpr int HOSTAGE_PENALTY = -25;
constexpr int MISSED_THREAT = -5;
constexpr int STRAY = -5;
constexpr int HELD_FIRE = 2;
constexpr uint32_t COMBO_TIMEOUT_MS = 4000;
constexpr uint32_t INPUT_MASK_MS = 150;

class ShootNoShoot : public GameMode {
 public:
  using GameMode::GameMode;

  bool configure(JsonObjectConst cfg, std::string& err) override {
    duration_min_ = cfgInt(cfg, "duration", 2, 1, 10, err);
    if (!err.empty()) return false;
    if (!cfgEnum(cfg, "difficulty", "Normal", difficulty::NAMES, difficulty::COUNT, diff_, err)) return false;
    di_ = difficulty::index(diff_);
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
      if (countdown_.tick(host_)) {
        state_ = State::Playing;
        start_ = now;
        end_ = now + duration_min_ * 60000UL;
        next_spawn_ = now;
        last_hit_ = now;
        last_second_ = -1;
        host_.hudChanged();
      }
      int c = countdown_.secondsLeft(now);
      if (c != countdown_shown_) {
        countdown_shown_ = c;
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

    for (size_t i = 0; i < active_.size();) {
      Active& a = active_[i];
      if (a.switch_at && static_cast<int32_t>(now - a.switch_at) >= 0) {
        a.switch_at = 0;
        a.threat = !a.threat;
        a.at = now;
        a.expires = now + window(a.threat);
        host_.led(a.slot, a.threat ? led::red() : led::green());
      }
      if (static_cast<int32_t>(now - a.expires) >= 0) {
        if (a.threat) {
          score_ += MISSED_THREAT;
          missed_++;
          combo_ = 0;
          host_.feed(a.slot, MISSED_THREAT, -1, "threat missed");
        } else {
          score_ += HELD_FIRE;
          held_++;
          host_.feed(a.slot, HELD_FIRE, -1, "held fire");
        }
        host_.led(a.slot, led::off());
        active_.erase(active_.begin() + i);
        host_.hudChanged();
        continue;
      }
      i++;
    }

    int min_active = std::max<int>(1, difficulty::MIN_TARGETS[di_][stage_]);
    min_active = std::min<int>(min_active, host_.slots().size());
    int needed = min_active - static_cast<int>(active_.size());
    if (needed > 0 && static_cast<int32_t>(now - next_spawn_) >= 0) {
      for (int i = 0; i < needed; i++) spawn(now);
    }
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
    if (it == active_.end()) {
      score_ += STRAY;
      combo_ = 0;
      host_.feed(slot, STRAY, -1, "dark target");
      host_.hudChanged();
      return;
    }
    Active a = *it;
    active_.erase(it);
    host_.led(slot, led::off());
    mask_end_ = now + INPUT_MASK_MS;
    next_spawn_ = now + difficulty::spawnDelayMs(stage_);
    spawner_.hit(slot);
    if (!a.threat) {
      score_ += HOSTAGE_PENALTY;
      hostages_hit_++;
      combo_ = 0;
      host_.ledAll(led::flash(255, 0, 0, 600));
      host_.feed(slot, HOSTAGE_PENALTY, -1, "HOSTAGE HIT");
      host_.hudChanged();
      return;
    }
    uint32_t rt = (node_rt != proto::RT_NONE && !a.switched) ? node_rt : now - a.at;
    int points = rt < 750 ? 10 : rt <= 1400 ? 5 : 2;
    last_hit_ = now;
    combo_++;
    max_combo_ = std::max(max_combo_, combo_);
    if (combo_ > 3) points = points * 3 / 2;
    score_ += points;
    stats_.add(slot, rt);
    host_.feed(slot, points, static_cast<int>(rt), combo_ > 3 ? "x1.5" : "");
    host_.hudChanged();
  }

  void onNodeLost(uint8_t slot) override {
    active_.erase(std::remove_if(active_.begin(), active_.end(), [&](const Active& a) { return a.slot == slot; }),
                  active_.end());
  }

  void hud(JsonObject o) const override {
    o["status"] = state_ == State::Countdown ? "GET READY" : state_ == State::Playing ? "GO" : "OVER";
    o["score"] = score_;
    o["combo"] = combo_;
    o["hits"] = stats_.total_hits;
    o["hostages_hit"] = hostages_hit_;
    o["missed"] = missed_;
    if (state_ == State::Countdown) o["countdown"] = countdown_.secondsLeft(host_.now());
    o["time_left"] = state_ == State::Playing ? last_second_ : (state_ == State::Countdown ? duration_min_ * 60 : 0);
    o["time_total"] = duration_min_ * 60;
  }

  void result(JsonObject o) const override {
    o["hits"] = stats_.total_hits;
    o["hostages_hit"] = hostages_hit_;
    o["missed"] = missed_;
    o["held"] = held_;
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
    bool threat;
    uint32_t at;
    uint32_t expires;
    uint32_t switch_at;  // 0 = won't switch
    bool switched;
  };

  uint32_t window(bool threat) const {
    return threat ? TUNING[di_].threat_window_ms : TUNING[di_].hostage_window_ms;
  }

  void spawn(uint32_t now) {
    std::vector<uint8_t> busy;
    bool has_threat = false;
    for (auto& a : active_) {
      busy.push_back(a.slot);
      has_threat |= a.threat;
    }
    uint8_t s = spawner_.pick(host_, busy);
    if (!s) return;
    // Never light only hostages at once: with others lit, at least one is a threat.
    // A single target on its own may be a hostage (hold fire until it goes dark).
    bool threat = (!busy.empty() && !has_threat) || host_.random(100) >= TUNING[di_].hostage_pct;
    Active a{s, threat, now, now + window(threat), 0, false};
    if (TUNING[di_].switch_pct && host_.random(100) < TUNING[di_].switch_pct) {
      a.switch_at = now + window(threat) / 2;
      a.switched = true;
    }
    active_.push_back(a);
    host_.led(s, threat ? led::red() : led::green());
  }

  int duration_min_ = 2;
  std::string diff_ = "Normal";
  int di_ = 1;
  State state_ = State::Countdown;
  Countdown countdown_;
  Spawner spawner_;
  std::vector<Active> active_;
  SlotStats stats_;
  long score_ = 0;
  int combo_ = 0, max_combo_ = 0, missed_ = 0, held_ = 0, hostages_hit_ = 0, stage_ = 0, last_second_ = -1;
  int countdown_shown_ = -1;
  uint32_t start_ = 0, end_ = 0, next_spawn_ = 0, last_hit_ = 0, mask_end_ = 0;
};

GameMode* create(GameHost& h) { return new ShootNoShoot(h); }

}  // namespace

extern const ModeInfo MODE_SHOOT_NO_SHOOT = {"shoot_no_shoot", SCHEMA, 2, create};
