// ESP32 implementations of the hub core's ports: ESP-NOW radio, LittleFS
// files, WebSocket events and the serial log.
#pragma once

#include <Arduino.h>
#include <AsyncWebSocket.h>
#include <esp_now.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

#include <vector>

#include "ports.h"
#include "protocol.h"

// Frames and send results arrive on the WiFi task; they are queued here and
// handed to the hub from loop().
struct RxFrame {
  uint8_t mac[6];
  int8_t rssi;
  uint8_t len;
  uint8_t data[proto::MAX_FRAME];
};
struct TxResult {
  uint8_t mac[6];
  bool ok;
};

class Esp32Radio : public RadioPort {
 public:
  bool begin();
  bool send(const Mac& mac, const uint8_t* data, size_t len) override;
  void addPeer(const Mac& mac) override;
  void removePeer(const Mac& mac) override;
  bool popFrame(RxFrame& out) { return xQueueReceive(rx_, &out, 0) == pdTRUE; }
  bool popResult(TxResult& out) { return xQueueReceive(tx_, &out, 0) == pdTRUE; }
  uint32_t dropped() const { return dropped_; }

 private:
  static void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len);
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 5, 0)
  static void onSent(const wifi_tx_info_t* info, esp_now_send_status_t status);
#else
  static void onSent(const uint8_t* mac, esp_now_send_status_t status);
#endif
  bool ensurePeer(const Mac& mac);
  QueueHandle_t rx_ = nullptr;
  QueueHandle_t tx_ = nullptr;
  volatile uint32_t dropped_ = 0;
  std::vector<Mac> paired_;  // peers of online targets (addPeer)
  std::vector<Mac> temp_;    // short-lived peers for Welcome replies to new targets
  static Esp32Radio* self_;
};

class LittleFsStore : public Fs {
 public:
  bool begin();
  bool read(const char* path, std::string& out) override;
  bool write(const char* path, const std::string& data) override;
  bool append(const char* path, const std::string& data) override;
  bool readAt(const char* path, uint32_t offset, uint8_t* buf, size_t len) override;
  bool exists(const char* path) override;
  bool remove(const char* path) override;
  size_t size(const char* path) override;
};

class WsEvents : public EventSink {
 public:
  explicit WsEvents(AsyncWebSocket& ws) : ws_(ws) {}
  void emit(const std::string& json) override { ws_.textAll(json.c_str(), json.size()); }
  size_t clients() const override { return ws_.count(); }

 private:
  AsyncWebSocket& ws_;
};

class SerialLog : public Log {
 public:
  void line(const char* msg) override {
    Serial.printf("[%7lu] %s\n", static_cast<unsigned long>(millis() / 1000), msg);
  }
};

// The one lock around the hub (loop task vs. web handlers)
class HubLock {
 public:
  static void init() { mutex_ = xSemaphoreCreateRecursiveMutex(); }
  HubLock() : ok_(xSemaphoreTakeRecursive(mutex_, pdMS_TO_TICKS(500)) == pdTRUE) {}
  ~HubLock() {
    if (ok_) xSemaphoreGiveRecursive(mutex_);
  }
  bool ok() const { return ok_; }

 private:
  static SemaphoreHandle_t mutex_;
  bool ok_;
};
