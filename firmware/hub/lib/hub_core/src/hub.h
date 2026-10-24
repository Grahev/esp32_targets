// The hub: owns the targets, the running game, settings and records. Single
// threaded: the ESP32 glue calls every method from one task (radio callbacks
// are queued, web handlers take the hub lock), and the host tests call it
// directly with a virtual clock.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include <memory>
#include <string>
#include <vector>

#include "game.h"
#include "node_registry.h"
#include "ports.h"
#include "protocol.h"
#include "records.h"
#include "settings.h"
#include "virtual_nodes.h"

struct ApiResult {
  int code = 200;
  std::string msg;      // shown to the user on errors
  std::string confirm;  // non-empty: the app may retry with force=true (e.g. "low_battery")
  static ApiResult ok(const std::string& m = "OK") { return ApiResult{200, m, ""}; }
  static ApiResult err(int code, const std::string& m) { return ApiResult{code, m, ""}; }
};

class Hub : public GameHost {
 public:
  static constexpr uint32_t IDLE_AFTER_GAME_MS = 10000;
  static constexpr uint32_t LED_REFRESH_MS = 2000;  // lit targets are re-sent: a dead one is noticed fast
  static constexpr uint32_t PENDING_EXPIRE_MS = 30000;
  static constexpr uint32_t RETRY_MS = 250;
  static constexpr uint8_t RETRIES = 4;
  static constexpr uint8_t SEND_FAILS_OFFLINE = 2;
  static constexpr uint32_t WIFI_APPLY_DELAY_MS = 1500;
  static constexpr const char* NODE_OTA_PATH = "/ota/node.bin";

  Hub(RadioPort& radio, Fs& fs, EventSink& events, Log& log);
  ~Hub();

  void begin(uint32_t now, uint32_t seed, bool safe_mode = false);
  void onFrame(const Mac& mac, const uint8_t* data, size_t len, int8_t rssi);
  void onSendResult(const Mac& mac, bool ok);
  void tick(uint32_t now);

  // --- app API (all return quickly) ---
  void stateJson(JsonObject o);
  void nodesJson(JsonObject o);
  ApiResult updateSettings(JsonObjectConst in);
  ApiResult acceptNode(const Mac& mac);
  ApiResult forgetNode(const Mac& mac);
  ApiResult updateNode(const Mac& mac, JsonObjectConst in);
  ApiResult identifyNode(const Mac& mac);
  ApiResult calibrateBattery(const Mac& mac, int measured_mv);
  ApiResult rebootNode(const Mac& mac);
  ApiResult simHit(const Mac& mac);
  ApiResult setSensorTest(bool on);
  ApiResult startGame(const std::string& mode, JsonObjectConst cfg, int player, bool force);
  ApiResult stopGame();
  ApiResult startNodeOta(uint32_t size, const uint8_t md5[16], JsonArrayConst macs);
  void setTime(uint64_t epoch_ms);
  void modesJson(std::string& out) const;

  const Settings& settings() const { return settings_; }
  Records& records() { return records_; }
  bool gameRunning() const { return game_ != nullptr; }
  bool otaRunning() const { return ota_.active; }
  bool safeMode() const { return safe_mode_; }
  uint32_t epochNow() const;
  // True once when the WiFi access point should be restarted with new settings
  bool wifiApplyDue(uint32_t now);
  // A broadcast "toast" in the app
  void toast(const char* level, const std::string& msg);

  // --- GameHost ---
  uint32_t now() const override { return now_; }
  const std::vector<uint8_t>& slots() const override { return slots_; }
  void led(uint8_t slot, const LedCmd& cmd) override;
  void ledAll(const LedCmd& cmd) override;
  void hudChanged() override { hud_dirty_ = true; }
  void feed(uint8_t slot, int points, int rt_ms, const char* note) override;
  uint32_t random(uint32_t n) override;
  void finish(bool save) override;

 private:
  struct PendingCmd {
    Mac mac;
    uint8_t type;
    uint16_t seq;
    uint8_t len;
    uint8_t data[proto::MAX_FRAME];
    uint8_t tries;
    uint32_t next_at;
  };

  struct NodeOta {
    bool active = false;
    std::vector<Mac> targets;
    size_t idx = 0;
    uint32_t size = 0;
    uint8_t md5[16] = {0};
    enum class Phase { Begin, Data, End, Reboot } phase = Phase::Begin;
    uint32_t offset = 0;
    uint16_t wait_seq = 0;
    uint8_t wait_type = 0;
    uint32_t sent_at = 0;
    uint8_t tries = 0;
    bool waiting = false;
    std::vector<std::string> done, failed;
    uint32_t last_emit = 0;
  };

  // radio
  proto::Header header(proto::Msg type, uint8_t slot);
  void radioSend(const Mac& mac, const uint8_t* data, size_t len);
  void sendReliable(NodeRec& n, const uint8_t* data, size_t len);
  void sendWelcome(const Mac& mac, uint8_t slot, bool accepted);
  void sendSetMode(NodeRec& n);
  void sendConfig(NodeRec& n);
  void sendAck(NodeRec& n, proto::Msg type, uint16_t seq);
  void retryPending();
  void dropPending(const Mac& mac);

  // targets
  void handleHello(const Mac& mac, const proto::Header& h, const proto::Hello& p, int8_t rssi);
  void handleHeartbeat(const Mac& mac, const proto::Header& h, const proto::Heartbeat& p, int8_t rssi);
  void handleHit(NodeRec& n, const proto::Hit& p);
  void handleAck(NodeRec& n, const proto::Ack& p);
  NodeRec* admit(const Mac& mac);
  void seen(NodeRec& n, int8_t rssi);
  void nodeOnline(NodeRec& n);
  void nodeOffline(NodeRec& n, const char* why);
  void checkLiveness();
  void rebuildSlots();
  void refreshLeds();
  void syncVirtualNodes();
  void saveNodes();

  // game
  void setSystemMode(proto::Mode m);
  void endGame(bool natural, bool save);
  void processFinish();
  void gameJson(JsonObject o);

  // OTA
  void otaTick();
  void otaOnAck(NodeRec& n, const proto::Ack& a);
  void otaSend(NodeRec& n);
  void otaNextTarget(bool ok);
  void otaJson(JsonObject o);
  void emitOta(bool force);

  // events
  void emit(JsonDocument& doc);
  void emitNodes();
  void flushEvents();

  RadioPort& radio_;
  Fs& fs_;
  EventSink& events_;
  Log& log_;
  Settings settings_;
  NodeRegistry reg_;
  Records records_;
  VirtualNodes vnodes_;
  std::vector<PendingCmd> pending_;
  std::vector<uint8_t> slots_;
  NodeOta ota_;

  uint32_t now_ = 0;
  uint32_t rng_ = 1;
  uint16_t seq_ = 0;
  proto::Mode sys_mode_ = proto::Mode::Idle;
  bool safe_mode_ = false;
  uint32_t last_liveness_ = 0;
  uint32_t idle_at_ = 0;  // 0 = no pending switch to Idle
  uint64_t epoch_base_ = 0;  // epoch seconds at now_ == 0; 0 = unknown
  uint32_t wifi_apply_at_ = 0;

  GameMode* game_ = nullptr;
  std::string game_mode_;
  int game_player_ = 0;
  bool finish_pending_ = false;
  bool finish_save_ = false;
  std::string last_result_;  // JSON, for apps that connect after the game

  bool hud_dirty_ = false;
  bool leds_dirty_ = false;
  bool nodes_dirty_ = false;
};
