// Everything a target does, without touching hardware: finding and pairing
// with the hub, the send queue with retries, hits, LED output and the OTA
// receiver. main.cpp wires it to ESP-NOW, the NeoPixel, the sensor IRQ and
// LittleFS; the host tests drive it directly.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "effects.h"
#include "hit_filter.h"
#include "protocol.h"

struct NodeConfig {
  uint8_t node_id = 0;
  uint16_t system_id = 0;  // 0 = not paired
  uint8_t hub_mac[6] = {0};
  bool has_hub = false;
  uint8_t channel = 1;
  uint8_t brightness = 150;
  uint16_t debounce_ms = 300;
  uint8_t glitch_edges = 1;
  uint16_t glitch_window_ms = 30;
  uint16_t batt_scale_uv = 4102;
  uint8_t hb_interval_s = 2;
  bool hit_flash = true;
  uint8_t led_pin = 0;
};

class NodeIo {
 public:
  virtual ~NodeIo() {}
  // mac == nullptr: broadcast. Returns false if the radio refused the frame;
  // otherwise exactly one onSendDone() follows.
  virtual bool send(const uint8_t* mac, const uint8_t* data, size_t len) = 0;
  virtual void setChannel(uint8_t channel) = 0;
  virtual void saveConfig(const NodeConfig& cfg) = 0;
  virtual void reboot() = 0;
  virtual bool otaBegin(uint32_t size, const uint8_t md5[16]) = 0;
  virtual bool otaWrite(const uint8_t* data, size_t len) = 0;
  virtual bool otaEnd() = 0;  // verifies the MD5
  virtual void otaAbort() = 0;
  virtual void log(const char* msg) = 0;
};

enum class LinkState : uint8_t { Searching, Pairing, Linked };

struct NodeInfo {
  uint8_t fw_major, fw_minor, fw_patch, hw_rev, caps;
};

class NodeLogic {
 public:
  static constexpr uint32_t HELLO_MS = 250;            // while searching
  static constexpr uint8_t HELLOS_PER_CHANNEL = 3;
  static constexpr uint32_t PAIRING_HELLO_MS = 1000;
  static constexpr uint32_t FORGET_SYSTEM_AFTER_MS = 60000;  // then answer any hub (shows as new target)
  static constexpr uint8_t MAX_MISSED_HEARTBEATS = 4;  // no reply from the hub -> search again
  static constexpr uint8_t SEND_ATTEMPTS = 3;
  static constexpr uint8_t MAX_FAIL_STREAK = 3;
  static constexpr uint32_t SEND_DONE_TIMEOUT_MS = 100;
  static constexpr uint32_t OTA_IDLE_TIMEOUT_MS = 10000;

  NodeLogic(NodeIo& io, NodeConfig& cfg, const NodeInfo& info);

  void begin(uint32_t now);
  void tick(uint32_t now);
  void onFrame(const uint8_t* mac, const uint8_t* data, size_t len, uint32_t now);
  void onSendDone(bool ok, uint32_t now);
  void onEdge(uint32_t ms);  // sensor edge, in time order
  void setBattery(uint16_t mv, uint8_t pct, uint8_t flags);

  Rgb led(uint32_t now) const;  // colour to show right now (brightness applied)

  LinkState state() const { return state_; }
  proto::Mode mode() const { return mode_; }
  uint8_t channel() const { return channel_; }
  uint16_t hitCount() const { return hit_count_; }
  bool otaActive() const { return ota_active_; }

 private:
  struct Frame {
    uint8_t data[proto::MAX_FRAME];
    uint8_t len;
    bool unicast;
    uint8_t attempts;
  };
  static constexpr uint8_t QUEUE_LEN = 8;

  // sending
  void enqueue(const uint8_t* data, size_t len, bool unicast);
  proto::Header header(proto::Msg type);
  void sendHello();
  void sendHeartbeat();
  void sendAck(proto::Msg type, uint16_t seq, proto::AckStatus status, uint32_t value = 0);
  void pumpQueue(uint32_t now);
  void popFront();
  void clearQueue();

  // state
  void enterSearching(uint32_t now);
  void onWelcome(const uint8_t* mac, const proto::Header& h, const proto::Welcome& w, uint32_t now);
  void onHubFrame(const proto::Header& h, const uint8_t* data, size_t len, uint32_t now);
  void applyConfig(const proto::Config& c);
  void setMode(proto::Mode m, uint32_t now);
  void handleHit(const HitResult& r);
  void otaReset();

  NodeIo& io_;
  NodeConfig& cfg_;
  NodeInfo info_;
  LinkState state_ = LinkState::Searching;
  proto::Mode mode_ = proto::Mode::Idle;
  uint8_t channel_ = 1;

  Frame queue_[QUEUE_LEN];
  uint8_t q_head_ = 0, q_count_ = 0;
  bool inflight_ = false;
  uint32_t inflight_at_ = 0;
  uint8_t fail_streak_ = 0;
  uint16_t seq_ = 0;

  uint32_t search_started_ = 0;
  uint32_t next_hello_ = 0;
  uint8_t hellos_on_channel_ = 0;
  uint32_t next_heartbeat_ = 0;
  uint8_t missed_heartbeats_ = 0;

  uint16_t batt_mv_ = 0;
  uint8_t batt_pct_ = proto::BATT_UNKNOWN;
  uint8_t batt_flags_ = 0;

  EffectPlayer effect_;
  HitFilter filter_;
  uint16_t hit_count_ = 0;
  uint32_t now_ = 0;  // time of the last tick/frame, for handlers without a timestamp
  uint32_t flash_until_ = 0;
  Rgb flash_color_{0, 0, 0};
  uint32_t identify_until_ = 0;
  uint32_t boot_ms_ = 0;

  bool ota_active_ = false;
  uint32_t ota_size_ = 0;
  uint32_t ota_next_ = 0;
  uint32_t ota_last_ = 0;
  bool reboot_pending_ = false;
  uint32_t reboot_at_ = 0;
  bool channel_switch_pending_ = false;
  uint8_t channel_switch_to_ = 1;
  uint32_t channel_switch_at_ = 0;
};
