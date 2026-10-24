// What the hub core needs from the platform. The ESP32 build implements these
// with ESP-NOW, LittleFS and the WebSocket server (src/); the host tests and the
// simulator implement them in memory.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <string>

struct Mac {
  uint8_t b[6] = {0};

  bool operator==(const Mac& o) const { return memcmp(b, o.b, 6) == 0; }
  bool operator!=(const Mac& o) const { return !(*this == o); }
  bool isVirtual() const { return b[0] == 0x02 && b[1] == 0 && b[2] == 0 && b[3] == 0 && b[4] == 0; }

  static Mac from(const uint8_t* p) {
    Mac m;
    memcpy(m.b, p, 6);
    return m;
  }
  static Mac virtualNode(uint8_t i) {
    Mac m;
    m.b[0] = 0x02;
    m.b[5] = i;
    return m;
  }
  // "485519edf4f4" (lower case, no separators): the form used in files and URLs
  std::string str() const {
    char s[13];
    snprintf(s, sizeof(s), "%02x%02x%02x%02x%02x%02x", b[0], b[1], b[2], b[3], b[4], b[5]);
    return s;
  }
  static bool parse(const char* s, Mac& out) {
    if (!s || strlen(s) != 12) return false;
    for (int i = 0; i < 6; i++) {
      unsigned v;
      char byte[3] = {s[2 * i], s[2 * i + 1], 0};
      if (sscanf(byte, "%2x", &v) != 1) return false;
      out.b[i] = static_cast<uint8_t>(v);
    }
    return true;
  }
};

class RadioPort {
 public:
  virtual ~RadioPort() {}
  // Unicast; the radio reports the MAC-layer result later via Hub::onSendResult
  virtual bool send(const Mac& mac, const uint8_t* data, size_t len) = 0;
  virtual void addPeer(const Mac& mac) = 0;
  virtual void removePeer(const Mac& mac) = 0;
};

// Files are small (settings, node list, top scores). write() is atomic
// (tmp + rename), so a power cut leaves the old or the new file, never half.
class Fs {
 public:
  virtual ~Fs() {}
  virtual bool read(const char* path, std::string& out) = 0;
  virtual bool write(const char* path, const std::string& data) = 0;
  virtual bool append(const char* path, const std::string& data) = 0;
  virtual bool readAt(const char* path, uint32_t offset, uint8_t* buf, size_t len) = 0;
  virtual bool exists(const char* path) = 0;
  virtual bool remove(const char* path) = 0;
  virtual size_t size(const char* path) = 0;
};

class EventSink {
 public:
  virtual ~EventSink() {}
  virtual void emit(const std::string& json) = 0;
  virtual size_t clients() const = 0;
};

class Log {
 public:
  virtual ~Log() {}
  virtual void line(const char* msg) = 0;
};
