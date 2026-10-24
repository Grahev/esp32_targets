// Free Practice (new in v2): one red target at a time, no score, no
// leaderboard. Shows every reaction time; good for warming up and for checking
// targets after setup.
#include "../game.h"
#include "slot_stats.h"

namespace {

const char SCHEMA[] = R"json({"id":"free_practice","name":"Free Practice","min_nodes":1,
"tagline":"Warm up. One target at a time, no score",
"rules":["One red target lights at a time. Hit it; the next one lights after a short random pause.",
"Your reaction time is shown for every hit. Nothing is saved to the leaderboard.",
"Runs until you press Stop, or for the time you set."],
"settings":[{"key":"duration","label":"Duration (0 = until stopped)","type":"int","min":0,"max":30,"def":0,"unit":"min"},
{"key":"pace","label":"Pace","type":"enum","options":["Relaxed","Normal","Fast"],"def":"Normal"}],
"presets":{"Relaxed":{"pace":"Relaxed"},"Fast":{"pace":"Fast"}}})json";

const char* const PACES[] = {"Relaxed", "Normal", "Fast"};
const uint16_t GAP_MIN[] = {1500, 800, 300};
const uint16_t GAP_MAX[] = {3000, 2000, 1000};

class FreePractice : public GameMode {
 public:
  using GameMode::GameMode;

  bool configure(JsonObjectConst cfg, std::string& err) override {
    duration_min_ = cfgInt(cfg, "duration", 0, 0, 30, err);
    if (!err.empty()) return false;
    if (!cfgEnum(cfg, "pace", "Normal", PACES, 3, pace_name_, err)) return false;
    for (int i = 0; i < 3; i++)
      if (pace_name_ == PACES[i]) pace_ = i;
    return true;
  }

  void start() override {
    countdown_.begin(host_);
    host_.hudChanged();
  }

  void tick() override {
    const uint32_t now = host_.now();
    if (!playing_) {
      if (countdown_.tick(host_)) {
        playing_ = true;
        start_ = now;
        next_ = now;
        host_.hudChanged();
      }
      int c = countdown_.secondsLeft(now);
      if (c != countdown_shown_) {
        countdown_shown_ = c;
        host_.hudChanged();
      }
      return;
    }
    if (duration_min_) {
      int32_t remaining = static_cast<int32_t>(start_ + duration_min_ * 60000UL - now);
      if (remaining <= 0) {
        playing_ = false;
        host_.finish(true);
        return;
      }
      int second = (remaining + 999) / 1000;
      if (second != last_second_) {
        last_second_ = second;
        host_.hudChanged();
      }
    }
    if (!lit_ && static_cast<int32_t>(now - next_) >= 0) light(now);
  }

  void onHit(uint8_t slot, uint16_t node_rt) override {
    if (!playing_) return;
    const uint32_t now = host_.now();
    if (!lit_ || slot != lit_) {
      host_.feed(slot, 0, -1, "dark target");
      return;
    }
    uint32_t rt = node_rt != proto::RT_NONE ? node_rt : now - lit_at_;
    stats_.add(slot, rt);
    last_rt_ = rt;
    host_.led(slot, led::off());
    last_ = lit_;
    lit_ = 0;
    next_ = now + GAP_MIN[pace_] + host_.random(GAP_MAX[pace_] - GAP_MIN[pace_]);
    host_.feed(slot, 0, static_cast<int>(rt), "");
    host_.hudChanged();
  }

  void onNodeLost(uint8_t slot) override {
    if (slot == lit_) lit_ = 0;
  }

  void hud(JsonObject o) const override {
    o["status"] = playing_ ? "PRACTICE" : "GET READY";
    o["hits"] = stats_.total_hits;
    o["avg_rt"] = stats_.avg();
    o["best_rt"] = stats_.best_rt;
    o["last_rt"] = last_rt_;
    if (!playing_) o["countdown"] = countdown_.secondsLeft(host_.now());
    if (duration_min_) {
      o["time_left"] = playing_ ? last_second_ : duration_min_ * 60;
      o["time_total"] = duration_min_ * 60;
    }
  }

  void result(JsonObject o) const override {
    o["hits"] = stats_.total_hits;
    o["avg_rt"] = stats_.avg();
    o["best_rt"] = stats_.best_rt;
    stats_.toJson(o["slots"].to<JsonArray>());
  }

  long score() const override { return stats_.total_hits; }
  bool saveable() const override { return false; }
  std::string label() const override { return pace_name_; }

 private:
  void light(uint32_t now) {
    const auto& slots = host_.slots();
    if (slots.empty()) return;
    std::vector<uint8_t> choices;
    for (uint8_t s : slots)
      if (s != last_ || slots.size() == 1) choices.push_back(s);
    lit_ = choices[host_.random(choices.size())];
    lit_at_ = now;
    host_.led(lit_, led::red());
  }

  int duration_min_ = 0;
  std::string pace_name_ = "Normal";
  int pace_ = 1;
  Countdown countdown_;
  bool playing_ = false;
  uint8_t lit_ = 0, last_ = 0;
  uint32_t lit_at_ = 0, next_ = 0, start_ = 0, last_rt_ = 0;
  int last_second_ = -1;
  int countdown_shown_ = -1;
  SlotStats stats_;
};

GameMode* create(GameHost& h) { return new FreePractice(h); }

}  // namespace

extern const ModeInfo MODE_FREE_PRACTICE = {"free_practice", SCHEMA, 1, create};
