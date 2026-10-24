// Radio protocol v3, shared by the hub (ESP32), the nodes (ESP8266) and the
// host tests. Every frame is one ESP-NOW packet (max 250 bytes on ESP8266):
//
//   Header (8 bytes) | payload (fixed struct for the message type)
//
// All fields are little-endian; both chips and x86 hosts are little-endian,
// so the packed structs are copied as-is. See docs/v2/PROTOCOL.md.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "protocol.h assumes a little-endian target"
#endif

namespace proto {

constexpr uint8_t MAGIC = 0xA7;
constexpr uint8_t VERSION = 3;
constexpr size_t MAX_FRAME = 250;
constexpr uint8_t MAX_NODES_HARD = 8;  // settings default to 5

enum class Msg : uint8_t {
  // Node -> hub
  Hello = 0x01,      // broadcast while searching, unicast while waiting to be accepted
  Heartbeat = 0x02,  // every hb_interval_s while linked
  Hit = 0x03,
  Ack = 0x04,        // reply to SetMode / Config / Ota* / Identify
  // Hub -> node
  Welcome = 0x81,    // reply to Hello (and to a heartbeat from an unknown node)
  SetMode = 0x82,
  Led = 0x83,
  Config = 0x84,
  Identify = 0x85,
  Channel = 0x86,
  OtaBegin = 0x87,
  OtaData = 0x88,
  OtaEnd = 0x89,
  Reboot = 0x8A,
  Forget = 0x8B,
  HubAck = 0x8C,     // answer to a Heartbeat (types below 0x80 are node -> hub only)
};

// System mode of a node (what its LED shows when no game effect is set)
enum class Mode : uint8_t {
  Idle = 0,       // dim blue; pulses when the battery is low
  Active = 1,     // game: LED shows the effect the hub sent
  Standby = 2,    // LED off (between games)
  Calibrate = 3,  // sensor test: green flash on every hit
};

enum class Effect : uint8_t {
  Off = 0,
  Solid = 1,
  Blink = 2,  // p1 = period ms, p2 = blink count (0 = forever), then off
  Pulse = 3,  // p1 = period ms (smooth breathe, forever)
  Flash = 4,  // p1 = on time ms, then off
  Ramp = 5,   // p1 = duration ms, brightness p2/255 -> full, then stays on
};

enum class AckStatus : uint8_t {
  Ok = 0,
  Error = 1,
  BadOffset = 2,
  Md5Mismatch = 3,
  NoSpace = 4,
  Busy = 5,
};

// Node flags (Hello / Heartbeat)
constexpr uint8_t FLAG_CHARGING = 0x01;
constexpr uint8_t FLAG_LOW_BATT = 0x02;
constexpr uint8_t FLAG_LIT = 0x04;  // an effect other than Off is showing

// Node capabilities (Hello)
constexpr uint8_t CAP_EFFECTS = 0x01;
constexpr uint8_t CAP_OTA = 0x02;
constexpr uint8_t CAP_BUZZER = 0x04;
constexpr uint8_t CAP_NODE_RT = 0x08;  // Hit.reaction_ms is measured on the node

constexpr uint8_t BATT_UNKNOWN = 255;   // batt_pct when no battery is connected
constexpr uint16_t RT_NONE = 0xFFFF;    // Hit.reaction_ms when the node wasn't lit

// Config keys (Config payload is a list of key/value pairs)
enum class Key : uint8_t {
  Brightness = 1,      // max LED level 0-255 (default 150, PRD limit)
  DebounceMs = 2,      // lockout after a hit (default 300)
  GlitchEdges = 3,     // edges needed within GlitchWindowMs to count a hit (default 1)
  GlitchWindowMs = 4,  // default 30
  BattScaleUv = 5,     // battery microvolts per ADC count (default 4102 = 4.2 V at 1024)
  HbIntervalS = 6,     // heartbeat period (default 2)
  HitFlash = 7,        // 1 = flash white on a hit in Active mode (default 1)
  LedPin = 8,          // 0 or 4; applied after a reboot
};

#pragma pack(push, 1)

struct Header {
  uint8_t magic;
  uint8_t version;
  uint16_t system_id;  // random per hub; 0 = node not paired to any hub yet
  uint8_t type;        // Msg
  uint8_t node_id;     // slot 1..N; 0 = not assigned
  uint16_t seq;        // per sender; de-dup and ACK matching
};

struct Hello {
  uint8_t fw_major, fw_minor, fw_patch;
  uint8_t hw_rev;
  uint8_t caps;
  uint8_t led_pin;
  uint16_t battery_mv;
  uint8_t batt_pct;
  uint8_t flags;
};

struct Heartbeat {
  uint16_t battery_mv;
  uint8_t batt_pct;
  uint8_t flags;
  uint8_t mode;
  uint8_t effect_id;  // id of the effect showing (lets the hub spot a lost LED command)
  uint32_t uptime_s;
  // Appended in 2.0.1; older nodes send 10 bytes and these read as 0
  uint8_t fw_major, fw_minor, fw_patch;
};

struct Hit {
  uint16_t reaction_ms;  // lit -> hit, measured on the node; RT_NONE if not lit
  uint8_t effect_id;     // effect that was showing when hit (0 = none)
  uint8_t edges;         // sensor edges counted for this hit (calibration aid)
  uint16_t hit_count;    // hits since boot (diagnostics)
  uint32_t uptime_ms;
};

struct Ack {
  uint8_t acked_type;
  uint16_t acked_seq;
  uint8_t status;   // AckStatus
  uint32_t value;   // OTA: next expected offset
};

struct Welcome {
  uint8_t node_id;     // slot assigned by the hub (0 while not accepted)
  uint8_t accepted;    // 0 = waiting for the user to tap "Add" in the app
  uint8_t channel;
  uint8_t hb_interval_s;
  uint8_t mode;        // current system mode
};

struct SetMode {
  uint8_t mode;
};

struct Led {
  uint8_t effect;  // Effect
  uint8_t r, g, b;
  uint16_t p1, p2;
  uint8_t effect_id;  // same id = re-send of the same effect: don't restart it
};

struct ConfigItem {
  uint8_t key;
  uint16_t value;
};

constexpr size_t MAX_CONFIG_ITEMS = 16;

struct Config {
  uint8_t count;
  ConfigItem items[MAX_CONFIG_ITEMS];
};

struct Identify {
  uint8_t seconds;
};

struct Channel {
  uint8_t channel;
  uint16_t switch_in_ms;
};

struct OtaBegin {
  uint32_t size;
  uint8_t md5[16];
};

constexpr size_t OTA_CHUNK = 200;

struct OtaData {
  uint32_t offset;
  uint8_t len;
  uint8_t data[OTA_CHUNK];
};

#pragma pack(pop)

static_assert(sizeof(Header) == 8, "header layout");
static_assert(sizeof(Hello) == 10, "hello layout");
static_assert(sizeof(Heartbeat) == 13, "heartbeat layout");
constexpr size_t HEARTBEAT_MIN = 10;  // 2.0.0 nodes
static_assert(sizeof(Hit) == 10, "hit layout");
static_assert(sizeof(Ack) == 8, "ack layout");
static_assert(sizeof(Led) == 9, "led layout");
static_assert(sizeof(Header) + sizeof(Config) <= MAX_FRAME, "config fits a frame");
static_assert(sizeof(Header) + sizeof(OtaData) <= MAX_FRAME, "ota chunk fits a frame");

inline Header makeHeader(Msg type, uint16_t system_id, uint8_t node_id, uint16_t seq) {
  Header h;
  h.magic = MAGIC;
  h.version = VERSION;
  h.system_id = system_id;
  h.type = static_cast<uint8_t>(type);
  h.node_id = node_id;
  h.seq = seq;
  return h;
}

// Writes header + payload into buf (at least MAX_FRAME bytes). Returns the frame length.
template <typename P>
inline size_t encode(uint8_t* buf, const Header& h, const P& payload, size_t payload_len = sizeof(P)) {
  memcpy(buf, &h, sizeof(Header));
  memcpy(buf + sizeof(Header), &payload, payload_len);
  return sizeof(Header) + payload_len;
}

inline size_t encodeEmpty(uint8_t* buf, const Header& h) {
  memcpy(buf, &h, sizeof(Header));
  return sizeof(Header);
}

// Variable-length payloads: only send what is used
inline size_t configLen(const Config& c) { return 1 + c.count * sizeof(ConfigItem); }
inline size_t otaDataLen(const OtaData& d) { return 5 + d.len; }

// Header check: magic, version and minimum length. Doesn't check system_id.
inline bool parseHeader(const uint8_t* buf, size_t len, Header& out) {
  if (len < sizeof(Header)) return false;
  memcpy(&out, buf, sizeof(Header));
  return out.magic == MAGIC && out.version == VERSION;
}

// Copies the payload. Shorter frames are rejected; for variable-length
// payloads pass the minimum length, and the rest is zero-filled.
template <typename P>
inline bool parsePayload(const uint8_t* buf, size_t len, P& out, size_t min_len = sizeof(P)) {
  if (len < sizeof(Header) + min_len) return false;
  size_t n = len - sizeof(Header);
  if (n > sizeof(P)) n = sizeof(P);
  memset(&out, 0, sizeof(P));
  memcpy(&out, buf + sizeof(Header), n);
  return true;
}

inline bool parseConfig(const uint8_t* buf, size_t len, Config& out) {
  if (!parsePayload(buf, len, out, 1)) return false;
  if (out.count > MAX_CONFIG_ITEMS) return false;
  return len >= sizeof(Header) + configLen(out);
}

inline bool parseOtaData(const uint8_t* buf, size_t len, OtaData& out) {
  if (!parsePayload(buf, len, out, 5)) return false;
  if (out.len > OTA_CHUNK) return false;
  return len >= sizeof(Header) + otaDataLen(out);
}

inline bool isNodeToHub(uint8_t type) { return type < 0x80; }

}  // namespace proto
