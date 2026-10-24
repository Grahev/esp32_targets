// In-memory platform for the hub core: files, radio, app events, and targets
// that run the real node logic (node_core) behind a lossy fake radio.
#pragma once

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "hub.h"
#include "node_logic.h"
#include "version.h"

struct MemFs : Fs {
  std::map<std::string, std::string> files;
  bool read(const char* p, std::string& out) override {
    auto it = files.find(p);
    if (it == files.end()) return false;
    out = it->second;
    return true;
  }
  bool write(const char* p, const std::string& d) override {
    files[p] = d;
    return true;
  }
  bool append(const char* p, const std::string& d) override {
    files[p] += d;
    return true;
  }
  bool readAt(const char* p, uint32_t off, uint8_t* buf, size_t len) override {
    auto it = files.find(p);
    if (it == files.end() || off + len > it->second.size()) return false;
    memcpy(buf, it->second.data() + off, len);
    return true;
  }
  bool exists(const char* p) override { return files.count(p) > 0; }
  bool remove(const char* p) override { return files.erase(p) > 0; }
  size_t size(const char* p) override {
    auto it = files.find(p);
    return it == files.end() ? 0 : it->second.size();
  }
};

struct Events : EventSink {
  std::vector<std::string> all;
  void emit(const std::string& json) override { all.push_back(json); }
  size_t clients() const override { return 1; }
  int count(const char* type) const {
    std::string key = std::string("\"t\":\"") + type + "\"";
    int n = 0;
    for (auto& e : all) n += e.find(key) != std::string::npos;
    return n;
  }
  std::string last(const char* type) const {
    std::string key = std::string("\"t\":\"") + type + "\"";
    for (auto it = all.rbegin(); it != all.rend(); ++it)
      if (it->find(key) != std::string::npos) return *it;
    return "";
  }
};

struct QuietLog : Log {
  bool echo = false;
  std::vector<std::string> lines;
  void line(const char* m) override {
    lines.push_back(m);
    if (echo) printf("  [hub] %s\n", m);
  }
};

// Deterministic randomness for the fakes
inline uint32_t fakeRand(uint32_t n) {
  static uint32_t s = 2463534242u;
  s ^= s << 13;
  s ^= s >> 17;
  s ^= s << 5;
  return n ? s % n : 0;
}

struct FakeRadio;

// A target running the real node logic, talking to the hub through FakeRadio
struct LinkedNode : NodeIo {
  Mac mac;
  NodeConfig cfg;
  std::unique_ptr<NodeLogic> logic;
  FakeRadio* radio;
  bool powered = true;
  bool done_pending = false;
  bool done_ok = true;
  std::vector<std::vector<uint8_t>> inbox;
  std::vector<uint8_t> ota;
  uint32_t ota_size = 0;
  int reboots = 0;
  int saves = 0;

  LinkedNode(FakeRadio* r, uint8_t i, uint32_t now) : radio(r) {
    mac.b[0] = 0x48;
    mac.b[1] = 0x55;
    mac.b[5] = i;
    NodeInfo info{TARGETS_FW_MAJOR, TARGETS_FW_MINOR, TARGETS_FW_PATCH, 1,
                  proto::CAP_EFFECTS | proto::CAP_OTA | proto::CAP_NODE_RT};
    logic.reset(new NodeLogic(*this, cfg, info));
    logic->setBattery(3900, 70, 0);
    logic->begin(now);
  }
  void powerCycle(uint32_t now) {  // reboot with the saved config
    inbox.clear();
    NodeInfo info{TARGETS_FW_MAJOR, TARGETS_FW_MINOR, TARGETS_FW_PATCH, 1,
                  proto::CAP_EFFECTS | proto::CAP_OTA | proto::CAP_NODE_RT};
    logic.reset(new NodeLogic(*this, cfg, info));
    logic->setBattery(3900, 70, 0);
    logic->begin(now);
  }

  bool send(const uint8_t* to, const uint8_t* data, size_t len) override;
  void setChannel(uint8_t) override {}
  void saveConfig(const NodeConfig&) override { saves++; }
  void reboot() override { reboots++; }
  bool otaBegin(uint32_t size, const uint8_t*) override {
    ota.clear();
    ota_size = size;
    return true;
  }
  bool otaWrite(const uint8_t* d, size_t n) override {
    ota.insert(ota.end(), d, d + n);
    return true;
  }
  bool otaEnd() override { return ota.size() == ota_size; }
  void otaAbort() override {}
  void log(const char*) override {}
};

struct FakeRadio : RadioPort {
  Hub* hub = nullptr;
  std::vector<std::unique_ptr<LinkedNode>> nodes;
  int loss_pct = 0;
  struct Result {
    Mac mac;
    bool ok;
  };
  std::vector<Result> results;
  struct Up {
    Mac from;
    std::vector<uint8_t> data;
  };
  std::vector<Up> uplink;
  std::vector<Mac> peers;
  int sent = 0;

  LinkedNode* find(const Mac& m) {
    for (auto& n : nodes)
      if (n->mac == m) return n.get();
    return nullptr;
  }
  bool lost() { return loss_pct && static_cast<int>(fakeRand(100)) < loss_pct; }

  bool send(const Mac& mac, const uint8_t* data, size_t len) override {
    sent++;
    LinkedNode* n = find(mac);
    bool ok = n && n->powered && !lost();
    if (ok) n->inbox.emplace_back(data, data + len);
    results.push_back(Result{mac, ok});
    return true;
  }
  void addPeer(const Mac& m) override {
    for (auto& p : peers)
      if (p == m) return;
    peers.push_back(m);
  }
  void removePeer(const Mac& m) override {
    for (size_t i = 0; i < peers.size(); i++)
      if (peers[i] == m) peers.erase(peers.begin() + i--);
  }

  // One step of the radio world: node -> hub frames, hub -> node frames, send results
  void step(uint32_t now) {
    std::vector<Up> up;
    up.swap(uplink);
    for (auto& u : up) hub->onFrame(u.from, u.data.data(), u.data.size(), -55);
    std::vector<Result> res;
    res.swap(results);
    for (auto& r : res) hub->onSendResult(r.mac, r.ok);
    for (auto& n : nodes) {
      if (!n->powered) continue;
      std::vector<std::vector<uint8_t>> in;
      in.swap(n->inbox);
      static const uint8_t HUB_MAC[6] = {0x3c, 0x8a, 0x1f, 0x7f, 0x70, 0x29};
      for (auto& f : in) n->logic->onFrame(HUB_MAC, f.data(), f.size(), now);
      if (n->done_pending) {
        n->done_pending = false;
        n->logic->onSendDone(n->done_ok, now);
      }
      n->logic->tick(now);
    }
  }
};

inline bool LinkedNode::send(const uint8_t* to, const uint8_t* data, size_t len) {
  (void)to;
  if (!powered) return false;
  done_pending = true;
  done_ok = !radio->lost();
  if (done_ok) radio->uplink.push_back(FakeRadio::Up{mac, std::vector<uint8_t>(data, data + len)});
  return true;
}

// Hub + radio + targets on a virtual clock (10 ms steps)
struct World {
  MemFs fs;
  FakeRadio radio;
  Events events;
  QuietLog log;
  Hub hub{radio, fs, events, log};
  uint32_t now = 1000;

  explicit World(bool start = true) {
    radio.hub = &hub;
    if (start) hub.begin(now, 42);
  }
  LinkedNode& addNode() {
    radio.nodes.emplace_back(new LinkedNode(&radio, static_cast<uint8_t>(radio.nodes.size() + 1), now));
    return *radio.nodes.back();
  }
  void run(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 10) {
      now += 10;
      radio.step(now);
      hub.tick(now);
    }
  }
  size_t online() { return hub.slots().size(); }
};

// Parse an event into a document
inline JsonDocument parse(const std::string& s) {
  JsonDocument d;
  deserializeJson(d, s);
  return d;
}
