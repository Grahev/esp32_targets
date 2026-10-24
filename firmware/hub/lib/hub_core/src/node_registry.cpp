#include "node_registry.h"

#include <algorithm>

namespace {
const char* PATH = "/nodes.json";

void ledJson(JsonObject o, const proto::Led& l) {
  o["e"] = l.effect;
  char rgb[8];
  snprintf(rgb, sizeof(rgb), "#%02x%02x%02x", l.r, l.g, l.b);
  o["c"] = rgb;
}
}  // namespace

void NodeRec::toJson(JsonObject o) const {
  o["mac"] = mac.str();
  o["slot"] = slot;
  o["name"] = name;
  o["color"] = color;
  o["virtual"] = virt;
  o["online"] = online;
  o["batt_mv"] = batt_mv;
  if (batt_pct != proto::BATT_UNKNOWN) o["batt_pct"] = batt_pct;
  o["rssi"] = rssi;
  char fwv[16];
  snprintf(fwv, sizeof(fwv), "%u.%u.%u", fw[0], fw[1], fw[2]);
  o["fw"] = fwv;
  o["uptime_s"] = uptime_s;
  o["hits"] = hits;
  JsonObject c = o["cfg"].to<JsonObject>();
  c["debounce_ms"] = cfg.debounce_ms;
  c["glitch_edges"] = cfg.glitch_edges;
  c["glitch_window_ms"] = cfg.glitch_window_ms;
  c["batt_scale_uv"] = cfg.batt_scale_uv;
  c["hit_flash"] = cfg.hit_flash;
  c["led_pin"] = cfg.led_pin;
  ledJson(o["led"].to<JsonObject>(), led);
}

void PendingNode::toJson(JsonObject o, uint32_t now) const {
  o["mac"] = mac.str();
  char fwv[16];
  snprintf(fwv, sizeof(fwv), "%u.%u.%u", fw[0], fw[1], fw[2]);
  o["fw"] = fwv;
  if (batt_pct != proto::BATT_UNKNOWN) o["batt_pct"] = batt_pct;
  o["age_s"] = (now - first_seen) / 1000;
}

NodeRec* NodeRegistry::byMac(const Mac& m) {
  for (auto& n : nodes)
    if (n.mac == m) return &n;
  return nullptr;
}

NodeRec* NodeRegistry::bySlot(uint8_t slot) {
  for (auto& n : nodes)
    if (n.slot == slot) return &n;
  return nullptr;
}

uint8_t NodeRegistry::freeSlot(uint8_t max_nodes) const {
  for (uint8_t s = 1; s <= max_nodes; s++) {
    bool used = false;
    for (auto& n : nodes) used |= n.slot == s;
    if (!used) return s;
  }
  return 0;
}

NodeRec& NodeRegistry::add(const Mac& m, uint8_t slot, bool virt) {
  NodeRec n;
  n.mac = m;
  n.slot = slot;
  n.virt = virt;
  char name[24];
  snprintf(name, sizeof(name), virt ? "Sim %u" : "Target %u", slot);
  n.name = name;
  n.color = slot % 8;
  nodes.push_back(n);
  sort();
  return *byMac(m);
}

void NodeRegistry::remove(const Mac& m) {
  nodes.erase(std::remove_if(nodes.begin(), nodes.end(), [&](const NodeRec& n) { return n.mac == m; }), nodes.end());
}

NodeRec* NodeRegistry::moveTo(NodeRec& n, uint8_t slot) {
  Mac me = n.mac;
  Mac other_mac;
  NodeRec* other = bySlot(slot);
  bool swapped = other && other->mac != me;
  if (swapped) {
    other->slot = n.slot;
    other_mac = other->mac;
  }
  n.slot = slot;
  sort();  // invalidates pointers
  return swapped ? byMac(other_mac) : nullptr;
}

void NodeRegistry::sort() {
  std::sort(nodes.begin(), nodes.end(), [](const NodeRec& a, const NodeRec& b) { return a.slot < b.slot; });
}

std::vector<uint8_t> NodeRegistry::onlineSlots() const {
  std::vector<uint8_t> out;
  for (auto& n : nodes)
    if (n.online) out.push_back(n.slot);
  return out;
}

size_t NodeRegistry::realCount() const {
  size_t c = 0;
  for (auto& n : nodes) c += !n.virt;
  return c;
}

PendingNode& NodeRegistry::touchPending(const Mac& m, uint32_t now) {
  for (auto& p : pending) {
    if (p.mac == m) {
      p.last_seen = now;
      return p;
    }
  }
  if (pending.size() >= 8) pending.erase(pending.begin());
  PendingNode p;
  p.mac = m;
  p.first_seen = p.last_seen = now;
  pending.push_back(p);
  return pending.back();
}

void NodeRegistry::dropPending(const Mac& m) {
  pending.erase(std::remove_if(pending.begin(), pending.end(), [&](const PendingNode& p) { return p.mac == m; }),
                pending.end());
}

void NodeRegistry::expirePending(uint32_t now, uint32_t max_age_ms) {
  pending.erase(std::remove_if(pending.begin(), pending.end(),
                               [&](const PendingNode& p) { return now - p.last_seen > max_age_ms; }),
                pending.end());
}

bool NodeRegistry::load(Fs& fs) {
  std::string s;
  if (!fs.read(PATH, s)) return false;
  JsonDocument doc;
  if (deserializeJson(doc, s)) return false;
  nodes.clear();
  for (JsonObjectConst o : doc.as<JsonArrayConst>()) {
    Mac m;
    if (!Mac::parse(o["mac"] | "", m)) continue;
    uint8_t slot = o["slot"] | 0;
    if (!slot || bySlot(slot) || byMac(m)) continue;
    NodeRec& n = add(m, slot, false);
    n.name = o["name"] | n.name.c_str();
    n.color = o["color"] | n.color;
    JsonObjectConst c = o["cfg"];
    n.cfg.debounce_ms = c["debounce_ms"] | n.cfg.debounce_ms;
    n.cfg.glitch_edges = c["glitch_edges"] | n.cfg.glitch_edges;
    n.cfg.glitch_window_ms = c["glitch_window_ms"] | n.cfg.glitch_window_ms;
    n.cfg.batt_scale_uv = c["batt_scale_uv"] | n.cfg.batt_scale_uv;
    n.cfg.hit_flash = c["hit_flash"] | n.cfg.hit_flash;
    n.cfg.led_pin = c["led_pin"] | n.cfg.led_pin;
  }
  return true;
}

bool NodeRegistry::save(Fs& fs) const {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  for (auto& n : nodes) {
    if (n.virt) continue;
    JsonObject o = arr.add<JsonObject>();
    o["mac"] = n.mac.str();
    o["slot"] = n.slot;
    o["name"] = n.name;
    o["color"] = n.color;
    JsonObject c = o["cfg"].to<JsonObject>();
    c["debounce_ms"] = n.cfg.debounce_ms;
    c["glitch_edges"] = n.cfg.glitch_edges;
    c["glitch_window_ms"] = n.cfg.glitch_window_ms;
    c["batt_scale_uv"] = n.cfg.batt_scale_uv;
    c["hit_flash"] = n.cfg.hit_flash;
    c["led_pin"] = n.cfg.led_pin;
  }
  std::string s;
  serializeJson(doc, s);
  return fs.write(PATH, s);
}
