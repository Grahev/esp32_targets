#include "platform.h"

#include <LittleFS.h>
#include <WiFi.h>

Esp32Radio* Esp32Radio::self_ = nullptr;
SemaphoreHandle_t HubLock::mutex_ = nullptr;

// ---------------------------------------------------------------- radio

bool Esp32Radio::begin() {
  self_ = this;
  rx_ = xQueueCreate(24, sizeof(RxFrame));
  tx_ = xQueueCreate(48, sizeof(TxResult));
  if (esp_now_init() != ESP_OK) return false;
  esp_now_register_recv_cb(onRecv);
  esp_now_register_send_cb(onSent);
  return true;
}

void Esp32Radio::onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (!self_ || len <= 0 || len > static_cast<int>(proto::MAX_FRAME)) return;
  RxFrame f;
  memcpy(f.mac, info->src_addr, 6);
  f.rssi = info->rx_ctrl ? static_cast<int8_t>(info->rx_ctrl->rssi) : 0;
  f.len = static_cast<uint8_t>(len);
  memcpy(f.data, data, len);
  if (xQueueSend(self_->rx_, &f, 0) != pdTRUE) self_->dropped_++;
}

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 5, 0)
void Esp32Radio::onSent(const wifi_tx_info_t* info, esp_now_send_status_t status) {
  if (!self_ || !info) return;
  TxResult r;
  memcpy(r.mac, info->des_addr, 6);
#else
void Esp32Radio::onSent(const uint8_t* mac, esp_now_send_status_t status) {
  if (!self_ || !mac) return;
  TxResult r;
  memcpy(r.mac, mac, 6);
#endif
  r.ok = status == ESP_NOW_SEND_SUCCESS;
  xQueueSend(self_->tx_, &r, 0);
}

bool Esp32Radio::ensurePeer(const Mac& mac) {
  if (esp_now_is_peer_exist(mac.b)) return true;
  // Keep a few temporary peers for targets that aren't paired yet
  bool paired = false;
  for (auto& p : paired_) paired |= p == mac;
  if (!paired) {
    if (temp_.size() >= 4) {
      esp_now_del_peer(temp_.front().b);
      temp_.erase(temp_.begin());
    }
    temp_.push_back(mac);
  }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, mac.b, 6);
  peer.channel = 0;  // the AP's current channel
  peer.ifidx = WIFI_IF_AP;
  peer.encrypt = false;
  esp_err_t e = esp_now_add_peer(&peer);
  if (e != ESP_OK && e != ESP_ERR_ESPNOW_EXIST) {
    Serial.printf("add_peer %s failed: %d\n", mac.str().c_str(), e);
    return false;
  }
  return true;
}

bool Esp32Radio::send(const Mac& mac, const uint8_t* data, size_t len) {
  if (!ensurePeer(mac)) return false;
  return esp_now_send(mac.b, data, len) == ESP_OK;
}

void Esp32Radio::addPeer(const Mac& mac) {
  for (auto& p : paired_)
    if (p == mac) return;
  paired_.push_back(mac);
  for (size_t i = 0; i < temp_.size(); i++)
    if (temp_[i] == mac) temp_.erase(temp_.begin() + i--);
  ensurePeer(mac);
}

void Esp32Radio::removePeer(const Mac& mac) {
  for (size_t i = 0; i < paired_.size(); i++)
    if (paired_[i] == mac) paired_.erase(paired_.begin() + i--);
  esp_now_del_peer(mac.b);
}

// ---------------------------------------------------------------- files

bool LittleFsStore::begin() {
  // The partition is labelled "littlefs" (partitions.csv); the library default is "spiffs"
  if (LittleFS.begin(false, "/littlefs", 10, "littlefs")) return true;
  Serial.println("LittleFS mount failed: formatting (first boot)");
  return LittleFS.begin(true, "/littlefs", 10, "littlefs");
}

bool LittleFsStore::read(const char* path, std::string& out) {
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  out.resize(f.size());
  size_t n = f.read(reinterpret_cast<uint8_t*>(&out[0]), out.size());
  f.close();
  out.resize(n);
  return true;
}

bool LittleFsStore::write(const char* path, const std::string& data) {
  // tmp + rename: a power cut leaves the old file or the new one, never half
  std::string tmp = std::string(path) + ".tmp";
  File f = LittleFS.open(tmp.c_str(), "w", true);
  if (!f) return false;
  size_t n = f.write(reinterpret_cast<const uint8_t*>(data.data()), data.size());
  f.close();
  if (n != data.size()) {
    LittleFS.remove(tmp.c_str());
    return false;
  }
  if (LittleFS.exists(path)) LittleFS.remove(path);
  return LittleFS.rename(tmp.c_str(), path);
}

bool LittleFsStore::append(const char* path, const std::string& data) {
  File f = LittleFS.open(path, "a", true);
  if (!f) return false;
  size_t n = f.write(reinterpret_cast<const uint8_t*>(data.data()), data.size());
  f.close();
  return n == data.size();
}

bool LittleFsStore::readAt(const char* path, uint32_t offset, uint8_t* buf, size_t len) {
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  bool ok = f.seek(offset) && f.read(buf, len) == len;
  f.close();
  return ok;
}

bool LittleFsStore::exists(const char* path) { return LittleFS.exists(path); }

bool LittleFsStore::remove(const char* path) { return LittleFS.remove(path); }

size_t LittleFsStore::size(const char* path) {
  File f = LittleFS.open(path, "r");
  if (!f) return 0;
  size_t s = f.size();
  f.close();
  return s;
}
