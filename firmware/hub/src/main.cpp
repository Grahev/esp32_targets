// Hub: ESP32 (no PSRAM). Runs the open WiFi access point (optional password),
// the web app, ESP-NOW to the targets, and the game. All game and target logic
// is in lib/hub_core; this file starts the hardware and runs the loop.
#include <Arduino.h>
#include <DNSServer.h>
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <esp_ota_ops.h>
#include <esp_wifi.h>

#include "hub.h"
#include "platform.h"
#include "version.h"
#include "web_api.h"

namespace {

constexpr uint8_t MAX_WS_CLIENTS = 6;
#ifndef DIAG_INTERVAL_MS
#define DIAG_INTERVAL_MS 60000  // status line on serial
#endif
constexpr uint32_t HEALTHY_AFTER_MS = 60000;  // then the boot counts as good
constexpr uint32_t CRASH_LOOP_LIMIT = 3;

// Survives a crash/reset (not a power cut): counts boots that didn't reach HEALTHY_AFTER_MS
RTC_NOINIT_ATTR uint32_t rtc_magic;
RTC_NOINIT_ATTR uint32_t rtc_bad_boots;
constexpr uint32_t RTC_MAGIC = 0x7A26E7B1;

Esp32Radio radio;
LittleFsStore store;
AsyncWebServer server(80);
AsyncWebSocket ws("/ws");
WsEvents events(ws);
SerialLog logger;
Hub hub(radio, store, events, logger);
DNSServer dns;

bool safe_mode = false;
bool marked_healthy = false;
uint32_t reboot_at = 0;
uint32_t last_diag = 0;
uint32_t last_ws_cleanup = 0;

void startAccessPoint() {
  const Settings& s = hub.settings();
  WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1), IPAddress(255, 255, 255, 0));
  const char* pass = s.password.empty() ? nullptr : s.password.c_str();
  bool ok = WiFi.softAP(s.name.c_str(), pass, s.channel, 0, 8);
  Serial.printf("AP \"%s\" (%s) channel %u: %s\n", s.name.c_str(), pass ? "WPA2" : "open", s.channel,
                ok ? "up" : "FAILED");
}

class Actions : public WebActions {
 public:
  void rebootIn(uint32_t ms) override { reboot_at = millis() + ms; }
  void factoryReset() override {
    const char* files[] = {"/settings.json", "/nodes.json", "/players.json", "/history.jsonl", Hub::NODE_OTA_PATH};
    for (const char* f : files) LittleFS.remove(f);
    for (auto& m : gameModes()) LittleFS.remove((String("/scores/") + m.id + ".json").c_str());
    rebootIn(800);
  }
  void diag(JsonObject o) override {
    o["fw"] = TARGETS_FW_VERSION;
    o["uptime_s"] = millis() / 1000;
    o["heap_free"] = ESP.getFreeHeap();
    o["heap_min"] = ESP.getMinFreeHeap();
    o["heap_max_block"] = ESP.getMaxAllocHeap();
    o["ws_clients"] = ws.count();
    o["wifi_clients"] = WiFi.softAPgetStationNum();
    o["radio_dropped"] = radio.dropped();
    o["fs_used"] = LittleFS.usedBytes();
    o["fs_total"] = LittleFS.totalBytes();
    o["safe_mode"] = safe_mode;
    o["reset_reason"] = static_cast<int>(esp_reset_reason());
  }
};
Actions actions;

// Serial console for testing without WiFi:
//   state | stop | start <mode> [json settings] | set <json settings> | sensor on|off
void serialConsole() {
  static String line;
  while (Serial.available()) {
    char c = Serial.read();
    if (c != '\n' && c != '\r') {
      if (line.length() < 200) line += c;
      continue;
    }
    if (line.isEmpty()) continue;
    String cmd = line;
    line = "";
    HubLock lock;
    if (!lock.ok()) continue;
    ApiResult r = ApiResult::ok();
    if (cmd == "state") {
      JsonDocument d;
      hub.stateJson(d.to<JsonObject>());
      serializeJson(d, Serial);
      Serial.println();
      continue;
    } else if (cmd == "stop") {
      r = hub.stopGame();
    } else if (cmd.startsWith("start ")) {
      String rest = cmd.substring(6);
      int sp = rest.indexOf(' ');
      String mode = sp < 0 ? rest : rest.substring(0, sp);
      JsonDocument cfg;
      if (sp > 0) deserializeJson(cfg, rest.substring(sp + 1));
      r = hub.startGame(mode.c_str(), cfg.as<JsonObjectConst>(), 0, true);
    } else if (cmd.startsWith("set ")) {
      JsonDocument d;
      deserializeJson(d, cmd.substring(4));
      r = hub.updateSettings(d.as<JsonObjectConst>());
    } else if (cmd.startsWith("sensor ")) {
      r = hub.setSensorTest(cmd.endsWith("on"));
    } else {
      r = ApiResult::err(400, "commands: state | stop | start <mode> [json] | set <json> | sensor on|off");
    }
    Serial.printf("> %d %s\n", r.code, r.msg.c_str());
  }
}

}  // namespace

// Arduino-ESP32: keep a freshly updated image "pending" until we say it is
// healthy, so a bootloader with rollback enabled can return to the old one.
bool verifyRollbackLater() { return true; }

void setup() {
  Serial.begin(115200);
  delay(50);
  Serial.printf("\nTarget hub fw %s\n", TARGETS_FW_VERSION);

  esp_reset_reason_t why = esp_reset_reason();
  bool crashed = why == ESP_RST_PANIC || why == ESP_RST_INT_WDT || why == ESP_RST_TASK_WDT || why == ESP_RST_WDT;
  if (rtc_magic != RTC_MAGIC) {
    rtc_magic = RTC_MAGIC;
    rtc_bad_boots = 0;
  }
  rtc_bad_boots = crashed ? rtc_bad_boots + 1 : 0;
  safe_mode = rtc_bad_boots >= CRASH_LOOP_LIMIT;
  if (safe_mode) Serial.printf("SAFE MODE after %u crashes: games off, web app on\n", rtc_bad_boots);

  HubLock::init();
  store.begin();
  LittleFS.mkdir("/scores");

  WiFi.persistent(false);
  WiFi.mode(WIFI_AP);
  hub.begin(millis(), esp_random(), safe_mode);  // loads settings (name, password, channel)
  startAccessPoint();
  esp_wifi_set_ps(WIFI_PS_NONE);
  if (!radio.begin()) Serial.println("ESP-NOW init FAILED");

  dns.start(53, "*", WiFi.softAPIP());  // captive portal: every name -> the hub
  MDNS.begin("targets");
  MDNS.addService("http", "tcp", 80);
  setupWeb(server, ws, hub, actions);
  server.begin();
  enableLoopWDT();
  Serial.printf("Ready: http://192.168.4.1  heap %u\n", ESP.getFreeHeap());
}

void loop() {
  const uint32_t now = millis();
  {
    HubLock lock;
    if (lock.ok()) {
      RxFrame f;
      for (int i = 0; i < 24 && radio.popFrame(f); i++) hub.onFrame(Mac::from(f.mac), f.data, f.len, f.rssi);
      TxResult r;
      for (int i = 0; i < 48 && radio.popResult(r); i++) hub.onSendResult(Mac::from(r.mac), r.ok);
      hub.tick(now);
      if (hub.wifiApplyDue(now)) startAccessPoint();
    }
  }
  dns.processNextRequest();
  serialConsole();

  if (now - last_ws_cleanup >= 1000) {
    last_ws_cleanup = now;
    ws.cleanupClients(MAX_WS_CLIENTS);  // drops the oldest beyond the limit
  }
  if (!marked_healthy && now > HEALTHY_AFTER_MS) {
    marked_healthy = true;
    rtc_bad_boots = 0;
    esp_ota_mark_app_valid_cancel_rollback();
  }
  if (now - last_diag >= DIAG_INTERVAL_MS) {
    last_diag = now;
    const Hub::RadioStats& r = hub.radioStats();
    Serial.printf("MEM free=%u min=%u block=%u ws=%u sta=%u | RX hello=%u hb=%u hit=%u ack=%u other=%u dup=%u drop=%u"
                  " | TX %u ok=%u fail=%u\n",
                  ESP.getFreeHeap(), ESP.getMinFreeHeap(), ESP.getMaxAllocHeap(), ws.count(),
                  WiFi.softAPgetStationNum(), r.rx_hello, r.rx_heartbeat, r.rx_hit, r.rx_ack, r.rx_other_system,
                  r.rx_dup, radio.dropped(), r.tx, r.tx_ok, r.tx_fail);
  }
  if (reboot_at && static_cast<int32_t>(now - reboot_at) >= 0) {
    Serial.println("Restarting");
    delay(100);
    ESP.restart();
  }
  delay(2);
}
