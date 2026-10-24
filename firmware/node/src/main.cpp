// Target node: ESP8266 Wemos D1 Mini. SW-420 on GPIO5 (D1), WS2812 on GPIO0
// (D3, or GPIO4/D2 on new nodes), battery on A0. All behaviour lives in
// lib/node_core (NodeLogic); this file connects it to the hardware.
//
// Serial console (115200): "hit" fakes a sensor hit, "info" prints the state,
// "forget" unpairs, "reboot".
#include <Adafruit_NeoPixel.h>
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <LittleFS.h>
#include <Updater.h>
#include <espnow.h>

extern "C" {
#include <user_interface.h>
}

#include "battery.h"
#include "node_logic.h"
#include "version.h"

namespace {

constexpr uint8_t SENSOR_PIN = 5;  // D1
constexpr uint32_t BATTERY_READ_MS = 2000;  // frequent ADC reads disturb the ESP8266 radio
const char* CONFIG_PATH = "/config.json";
uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

NodeConfig cfg;
Adafruit_NeoPixel strip(1, 0, NEO_GRB + NEO_KHZ800);

// --- sensor edges, captured in the IRQ ---
constexpr uint8_t EDGE_RING = 16;
volatile uint32_t edge_ms[EDGE_RING];
volatile uint8_t edge_head = 0, edge_tail = 0;

IRAM_ATTR void onSensor() {
  uint8_t next = (edge_head + 1) % EDGE_RING;
  if (next == edge_tail) return;  // full: a burst this long is one hit anyway
  edge_ms[edge_head] = millis();
  edge_head = next;
}

// --- received frames, copied in the ESP-NOW callback, handled in loop() ---
struct RxFrame {
  uint8_t mac[6];
  uint8_t len;
  uint8_t data[proto::MAX_FRAME];
};
constexpr uint8_t RX_RING = 4;
RxFrame rx[RX_RING];
volatile uint8_t rx_head = 0, rx_tail = 0;

void onRecv(uint8_t* mac, uint8_t* data, uint8_t len) {
  uint8_t next = (rx_head + 1) % RX_RING;
  if (next == rx_tail || len > proto::MAX_FRAME) return;
  memcpy(rx[rx_head].mac, mac, 6);
  memcpy(rx[rx_head].data, data, len);
  rx[rx_head].len = len;
  rx_head = next;
}

volatile uint8_t sent_ok = 0, sent_fail = 0;

void onSent(uint8_t* mac, uint8_t status) {
  (void)mac;
  if (status == 0) {
    sent_ok++;
  } else {
    sent_fail++;
  }
}

// --- config file ---
void loadConfig() {
  File f = LittleFS.open(CONFIG_PATH, "r");
  if (!f) {
    Serial.println("No config yet, the hub will assign a slot");
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, f)) {
    Serial.println("Config unreadable, using defaults");
    f.close();
    return;
  }
  f.close();
  cfg.node_id = doc["node_id"] | 0;
  cfg.system_id = doc["system_id"] | 0;
  const char* mac = doc["hub_mac"] | "";
  unsigned int m[6];
  if (sscanf(mac, "%2x%2x%2x%2x%2x%2x", &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) == 6) {
    for (int i = 0; i < 6; i++) cfg.hub_mac[i] = static_cast<uint8_t>(m[i]);
    cfg.has_hub = true;
  }
  cfg.channel = doc["channel"] | 1;
  cfg.brightness = doc["brightness"] | 150;
  cfg.debounce_ms = doc["debounce_ms"] | 300;
  cfg.glitch_edges = doc["glitch_edges"] | 1;
  cfg.glitch_window_ms = doc["glitch_window_ms"] | 30;
  cfg.batt_scale_uv = doc["batt_scale_uv"] | BATT_SCALE_DEFAULT_UV;
  cfg.hb_interval_s = doc["hb_interval_s"] | 2;
  cfg.hit_flash = doc["hit_flash"] | true;
  cfg.led_pin = doc["led_pin"] | 0;
}

void writeConfig(const NodeConfig& c) {
  JsonDocument doc;
  doc["node_id"] = c.node_id;
  doc["system_id"] = c.system_id;
  if (c.has_hub) {
    char mac[13];
    snprintf(mac, sizeof(mac), "%02x%02x%02x%02x%02x%02x", c.hub_mac[0], c.hub_mac[1], c.hub_mac[2], c.hub_mac[3],
             c.hub_mac[4], c.hub_mac[5]);
    doc["hub_mac"] = mac;
  }
  doc["channel"] = c.channel;
  doc["brightness"] = c.brightness;
  doc["debounce_ms"] = c.debounce_ms;
  doc["glitch_edges"] = c.glitch_edges;
  doc["glitch_window_ms"] = c.glitch_window_ms;
  doc["batt_scale_uv"] = c.batt_scale_uv;
  doc["hb_interval_s"] = c.hb_interval_s;
  doc["hit_flash"] = c.hit_flash;
  doc["led_pin"] = c.led_pin;
  // tmp + rename: a power cut leaves the old or the new file, never half
  File f = LittleFS.open("/config.tmp", "w");
  if (!f) {
    Serial.println("Could not save config");
    return;
  }
  serializeJson(doc, f);
  f.close();
  LittleFS.remove(CONFIG_PATH);
  LittleFS.rename("/config.tmp", CONFIG_PATH);
}

// --- hardware side of NodeLogic ---
class Esp8266Io : public NodeIo {
 public:
  bool send(const uint8_t* mac, const uint8_t* data, size_t len) override {
    uint8_t* dst = mac ? const_cast<uint8_t*>(mac) : BROADCAST;
    if (mac && !esp_now_is_peer_exist(dst)) {
      esp_now_add_peer(dst, ESP_NOW_ROLE_COMBO, channel_, nullptr, 0);
    }
    return esp_now_send(dst, const_cast<uint8_t*>(data), len) == 0;
  }

  void setChannel(uint8_t channel) override {
    channel_ = channel;
    wifi_promiscuous_enable(1);
    wifi_set_channel(channel);
    wifi_promiscuous_enable(0);
    if (cfg.has_hub && esp_now_is_peer_exist(cfg.hub_mac)) {
      esp_now_del_peer(cfg.hub_mac);  // re-added on the new channel by send()
    }
  }

  void saveConfig(const NodeConfig& c) override { writeConfig(c); }

  void reboot() override {
    Serial.println("Rebooting");
    delay(50);
    ESP.restart();
  }

  bool otaBegin(uint32_t size, const uint8_t md5[16]) override {
    if (size > ESP.getFreeSketchSpace()) return false;
    if (!Update.begin(size, U_FLASH)) return false;
    char hex[33];
    for (int i = 0; i < 16; i++) snprintf(hex + 2 * i, 3, "%02x", md5[i]);
    Update.setMD5(hex);
    Serial.printf("OTA begin, %u bytes\n", static_cast<unsigned>(size));
    return true;
  }

  bool otaWrite(const uint8_t* data, size_t len) override {
    return Update.write(const_cast<uint8_t*>(data), len) == len;
  }

  bool otaEnd() override {
    bool ok = Update.end();  // checks the size and the MD5
    Serial.printf("OTA end: %s\n", ok ? "ok" : Update.getErrorString().c_str());
    return ok;
  }

  void otaAbort() override {
    Update.end(true);  // discard; the running firmware stays
    Serial.println("OTA aborted");
  }

  void log(const char* msg) override { Serial.println(msg); }

 private:
  uint8_t channel_ = 1;
};

Esp8266Io io;
const NodeInfo INFO{TARGETS_FW_MAJOR, TARGETS_FW_MINOR, TARGETS_FW_PATCH, 1,
                    proto::CAP_EFFECTS | proto::CAP_OTA | proto::CAP_NODE_RT};
NodeLogic logic(io, cfg, INFO);

uint32_t last_battery = 0;
Rgb shown{1, 1, 1};  // forces the first write

void readBattery() {
  uint16_t raw = analogRead(A0);
  uint16_t mv = batteryMv(raw, cfg.batt_scale_uv);
  logic.setBattery(mv, batteryPct(mv), 0);
}

const char* stateName(LinkState s) {
  switch (s) {
    case LinkState::Searching:
      return "searching";
    case LinkState::Pairing:
      return "pairing";
    case LinkState::Linked:
      return "linked";
  }
  return "?";
}

void serialConsole() {
  static char line[32];
  static uint8_t n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r') {
      if (n < sizeof(line) - 1) line[n++] = c;
      continue;
    }
    line[n] = 0;
    n = 0;
    if (!strcmp(line, "hit")) {
      onSensor();
    } else if (!strcmp(line, "info")) {
      Serial.printf("fw %s slot %u state %s mode %u ch %u sys %04x hits %u heap %u mac %s\n", TARGETS_FW_VERSION,
                    cfg.node_id, stateName(logic.state()), static_cast<unsigned>(logic.mode()), logic.channel(),
                    cfg.system_id, logic.hitCount(), ESP.getFreeHeap(), WiFi.macAddress().c_str());
    } else if (!strcmp(line, "forget")) {
      cfg = NodeConfig{};
      writeConfig(cfg);
      io.reboot();
    } else if (!strcmp(line, "reboot")) {
      io.reboot();
    }
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  Serial.println();
  Serial.printf("Target node fw %s\n", TARGETS_FW_VERSION);

  if (!LittleFS.begin()) {
    Serial.println("LittleFS mount failed, formatting");
    LittleFS.format();
    LittleFS.begin();
  }
  loadConfig();

  strip.setPin(cfg.led_pin == 4 ? 4 : 0);
  strip.begin();
  strip.clear();
  strip.show();

  pinMode(SENSOR_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(SENSOR_PIN), onSensor, RISING);

  // STA only (no open AP per target), never connecting to anything
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  if (esp_now_init() != 0) {
    Serial.println("ESP-NOW init failed, rebooting");
    delay(1000);
    ESP.restart();
  }
  esp_now_set_self_role(ESP_NOW_ROLE_COMBO);
  esp_now_register_recv_cb(onRecv);
  esp_now_register_send_cb(onSent);

  readBattery();
  logic.begin(millis());
  Serial.printf("MAC %s, slot %u\n", WiFi.macAddress().c_str(), cfg.node_id);
}

void loop() {
  uint32_t now = millis();

  while (edge_tail != edge_head) {
    logic.onEdge(edge_ms[edge_tail]);
    edge_tail = (edge_tail + 1) % EDGE_RING;
  }
  while (rx_tail != rx_head) {
    RxFrame& f = rx[rx_tail];
    logic.onFrame(f.mac, f.data, f.len, now);
    rx_tail = (rx_tail + 1) % RX_RING;
  }
  // Send results arrive in order; replay them to the logic
  while (sent_ok || sent_fail) {
    noInterrupts();
    bool ok = sent_ok > 0;
    if (ok) {
      sent_ok--;
    } else {
      sent_fail--;
    }
    interrupts();
    logic.onSendDone(ok, now);
  }

  if (now - last_battery >= BATTERY_READ_MS) {
    last_battery = now;
    readBattery();
  }

  logic.tick(now);

  Rgb c = logic.led(now);
  if (c != shown) {  // the NeoPixel write blocks interrupts briefly: only on change
    shown = c;
    strip.setPixelColor(0, c.r, c.g, c.b);
    strip.show();
  }

  serialConsole();
  delay(1);
}
