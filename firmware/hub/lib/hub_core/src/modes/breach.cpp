// The Breach (ported from v1 mode_breach.py): a memory game with 10 levels.
// The targets flash a blue sequence (3 long, up to 9), then the player hits
// them in order. A wrong target, or more than 5 s between hits, ends the game.
// Each level scores (100 + time bonus against par, 2 s per target) x 1.2.
// v2 fixes: a correct hit flashes green and turns off (v1 #20); hits and
// reaction times are recorded and 0-point games aren't saved (v1 #24).
#include <algorithm>

#include "../game.h"
#include "slot_stats.h"

namespace {

const char SCHEMA[] = R"json({"id":"breach","name":"The Breach","min_nodes":1,
"tagline":"Memorise the sequence, then hit it in order",
"rules":["Watch: targets flash blue one after another.",
"When all targets flash green, hit them in the same order.",
"A wrong target, or more than 5 s between hits, ends the game.",
"10 levels; sequences grow from 3 to 9 targets and flash faster. Beat the par time (2 s per target) for bonus points."],
"settings":[{"key":"start_level","label":"Start at level","type":"int","min":1,"max":10,"def":1}],
"presets":{"From the start":{"start_level":1},"Skip ahead":{"start_level":4}}})json";

struct LevelSpec {
  uint8_t length;
  uint16_t flash_ms;
};
const LevelSpec LEVELS[10] = {{3, 700}, {3, 700}, {4, 500}, {5, 500}, {5, 500},
                              {6, 400}, {6, 400}, {7, 400}, {8, 300}, {9, 300}};
constexpr int MAX_LEVEL = 10;
constexpr uint32_t GAP_MS = 300;
constexpr uint32_t READY_MS = 1500;
constexpr uint32_t GO_MS = 200;
constexpr uint32_t HIT_TIMEOUT_MS = 5000;
constexpr uint32_t PAR_PER_TARGET_MS = 2000;
constexpr uint32_t BETWEEN_LEVELS_MS = 2000;
constexpr uint32_t FAIL_SHOW_MS = 2000;
constexpr uint32_t INPUT_MASK_MS = 150;

class Breach : public GameMode {
 public:
  using GameMode::GameMode;

  bool configure(JsonObjectConst cfg, std::string& err) override {
    start_level_ = cfgInt(cfg, "start_level", 1, 1, MAX_LEVEL, err);
    return err.empty();
  }

  void start() override {
    level_ = start_level_;
    startLevel();
  }

  void tick() override {
    const uint32_t now = host_.now();
    bool due = static_cast<int32_t>(now - next_) >= 0;
    switch (state_) {
      case State::Countdown:
        if (countdown_.tick(host_)) {
          state_ = State::Flashing;
          flash_idx_ = 0;
          next_ = now + 500;
        }
        break;
      case State::Flashing:
        if (!due) break;
        if (flash_idx_ >= sequence_.size()) {
          state_ = State::Ready;
          next_ = now + READY_MS;
          setStatus("READY?");
          break;
        }
        host_.led(sequence_[flash_idx_], led::flash(0, 0, 255, spec().flash_ms));
        flash_idx_++;
        next_ = now + spec().flash_ms + GAP_MS;
        break;
      case State::Ready:
        if (!due) break;
        state_ = State::Go;
        host_.ledAll(led::flash(0, 255, 0, GO_MS));
        next_ = now + GO_MS;
        break;
      case State::Go:
        if (!due) break;
        state_ = State::Playing;
        idx_ = 0;
        round_start_ = last_hit_ = now;
        setStatus("GO!");
        break;
      case State::Playing:
        if (now - last_hit_ > HIT_TIMEOUT_MS) fail("TOO SLOW");
        break;
      case State::LevelDone:
        if (!due) break;
        if (level_ < MAX_LEVEL) {
          level_++;
          startLevel();
        } else {
          cleared_all_ = true;
          state_ = State::Done;
          host_.finish(true);
        }
        break;
      case State::Failed:
        if (!due) break;
        state_ = State::Done;
        host_.finish(true);
        break;
      case State::Done:
        break;
    }
  }

  void onHit(uint8_t slot, uint16_t node_rt) override {
    (void)node_rt;
    if (state_ != State::Playing) return;
    const uint32_t now = host_.now();
    if (mask_end_ && static_cast<int32_t>(mask_end_ - now) > 0) return;
    if (slot != sequence_[idx_]) {
      host_.feed(slot, 0, -1, "wrong target");
      fail("WRONG TARGET");
      return;
    }
    host_.led(slot, led::flash(0, 255, 0, 300));
    mask_end_ = now + INPUT_MASK_MS;
    uint32_t split = now - last_hit_;
    stats_.add(slot, split);
    last_hit_ = now;
    idx_++;
    host_.feed(slot, 0, static_cast<int>(split), "");
    if (idx_ < sequence_.size()) {
      host_.hudChanged();
      return;
    }
    // Level cleared
    uint32_t par = spec().length * PAR_PER_TARGET_MS;
    uint32_t taken = now - round_start_;
    long points = 100;
    if (taken < par) points += (par - taken) / 100 * 5;
    points = points * 6 / 5;  // precision bonus, on this level's points only (v1 #13)
    score_ += points;
    levels_cleared_++;
    state_ = State::LevelDone;
    next_ = now + BETWEEN_LEVELS_MS;
    host_.feed(0, static_cast<int>(points), static_cast<int>(taken), "level cleared");
    setStatus("CLEARED");
  }

  void onNodeLost(uint8_t slot) override {
    if (state_ == State::Failed || state_ == State::Done || state_ == State::LevelDone) return;
    if (std::find(sequence_.begin(), sequence_.end(), slot) == sequence_.end()) return;
    // The sequence can't be completed any more: replay the level with the targets left
    host_.ledAll(led::off());
    setStatus("TARGET LOST");
    startLevel();
  }

  void hud(JsonObject o) const override {
    o["status"] = status_;
    o["score"] = score_;
    o["level"] = level_;
    o["levels"] = MAX_LEVEL;
    o["progress"] = state_ == State::Playing ? idx_ : 0;
    o["length"] = sequence_.size();
    if (state_ == State::Countdown) o["countdown"] = countdown_.secondsLeft(host_.now());
  }

  void result(JsonObject o) const override {
    o["level"] = level_;
    o["cleared"] = levels_cleared_;
    o["all_cleared"] = cleared_all_;
    o["hits"] = stats_.total_hits;
    o["avg_rt"] = stats_.avg();
    o["best_rt"] = stats_.best_rt;
    stats_.toJson(o["slots"].to<JsonArray>());
  }

  uint8_t nextExpected() const override { return state_ == State::Playing ? sequence_[idx_] : 0; }
  long score() const override { return score_; }
  bool saveable() const override { return score_ > 0; }
  std::string label() const override {
    return start_level_ == 1 ? "Standard" : "From level " + std::to_string(start_level_);
  }

 private:
  enum class State { Countdown, Flashing, Ready, Go, Playing, LevelDone, Failed, Done };

  const LevelSpec& spec() const { return LEVELS[level_ - 1]; }

  void setStatus(const char* s) {
    status_ = s;
    host_.hudChanged();
  }

  void startLevel() {
    const auto& slots = host_.slots();
    sequence_.clear();
    if (slots.empty()) {
      fail("NO TARGETS");
      return;
    }
    uint8_t last = 0;
    for (int i = 0; i < spec().length; i++) {
      // Avoid the same target twice in a row when there is a choice
      std::vector<uint8_t> choices;
      for (uint8_t s : slots)
        if (s != last || slots.size() == 1) choices.push_back(s);
      last = choices[host_.random(choices.size())];
      sequence_.push_back(last);
    }
    idx_ = 0;
    state_ = State::Countdown;
    countdown_.begin(host_);
    status_ = "WATCH";
    host_.hudChanged();
  }

  void fail(const char* why) {
    state_ = State::Failed;
    host_.ledAll(led::solid(255, 0, 0));
    next_ = host_.now() + FAIL_SHOW_MS;
    setStatus(why);
  }

  int start_level_ = 1;
  int level_ = 1;
  State state_ = State::Countdown;
  Countdown countdown_;
  std::vector<uint8_t> sequence_;
  size_t flash_idx_ = 0, idx_ = 0;
  uint32_t next_ = 0, round_start_ = 0, last_hit_ = 0, mask_end_ = 0;
  long score_ = 0;
  int levels_cleared_ = 0;
  bool cleared_all_ = false;
  const char* status_ = "WATCH";
  SlotStats stats_;
};

GameMode* create(GameHost& h) { return new Breach(h); }

}  // namespace

extern const ModeInfo MODE_BREACH = {"breach", SCHEMA, 1, create};
