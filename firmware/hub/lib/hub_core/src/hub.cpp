#include "hub.h"

#include <algorithm>

#include "version.h"

using proto::Header;
using proto::Mode;
using proto::Msg;

namespace {

const char* modeName(Mode m) {
  switch (m) {
    case Mode::Idle:
      return "idle";
    case Mode::Active:
      return "active";
    case Mode::Standby:
      return "standby";
    case Mode::Calibrate:
      return "sensor_test";
  }
  return "?";
}

bool persistentEffect(const proto::Led& l) {
  switch (static_cast<proto::Effect>(l.effect)) {
    case proto::Effect::Solid:
    case proto::Effect::Pulse:
    case proto::Effect::Ramp:
      return true;
    case proto::Effect::Blink:
      return l.p2 == 0;
    default:
      return false;
  }
}

}  // namespace

Hub::Hub(RadioPort& radio, Fs& fs, EventSink& events, Log& log)
    : radio_(radio), fs_(fs), events_(events), log_(log), records_(fs) {}

Hub::~Hub() { delete game_; }

void Hub::begin(uint32_t now, uint32_t seed, bool safe_mode) {
  now_ = now;
  rng_ = seed ? seed : 0x12345678;
  safe_mode_ = safe_mode;
  settings_.load(fs_);
  if (!settings_.system_id) {
    while (!settings_.system_id) settings_.system_id = static_cast<uint16_t>(random(65536));
    settings_.save(fs_);
  }
  reg_.load(fs_);
  records_.load();
  if (!safe_mode_) syncVirtualNodes();
  char line[96];
  snprintf(line, sizeof(line), "hub fw %s, system %04x, %u targets paired%s", TARGETS_FW_VERSION, settings_.system_id,
           static_cast<unsigned>(reg_.nodes.size()), safe_mode_ ? ", SAFE MODE" : "");
  log_.line(line);
}

// ================================================================ radio

Header Hub::header(Msg type, uint8_t slot) {
  return proto::makeHeader(type, settings_.system_id, slot, ++seq_);
}

void Hub::radioSend(const Mac& mac, const uint8_t* data, size_t len) {
  if (mac.isVirtual()) {
    vnodes_.deliver(&mac, data, len);
    return;
  }
  stats_.tx++;
  radio_.send(mac, data, len);
}

void Hub::sendReliable(NodeRec& n, const uint8_t* data, size_t len) {
  Header h;
  proto::parseHeader(data, len, h);
  if (h.type == static_cast<uint8_t>(Msg::SetMode) || h.type == static_cast<uint8_t>(Msg::Config)) {
    // a newer SetMode/Config replaces one still waiting for its ACK
    pending_.erase(std::remove_if(pending_.begin(), pending_.end(),
                                  [&](const PendingCmd& p) { return p.mac == n.mac && p.type == h.type; }),
                   pending_.end());
  }
  PendingCmd p;
  p.mac = n.mac;
  p.type = h.type;
  p.seq = h.seq;
  p.len = static_cast<uint8_t>(len);
  memcpy(p.data, data, len);
  p.tries = 1;
  p.next_at = now_ + RETRY_MS;
  pending_.push_back(p);
  radioSend(n.mac, data, len);
}

void Hub::retryPending() {
  for (size_t i = 0; i < pending_.size();) {
    PendingCmd& p = pending_[i];
    if (static_cast<int32_t>(now_ - p.next_at) < 0) {
      i++;
      continue;
    }
    if (p.tries >= RETRIES) {
      pending_.erase(pending_.begin() + i);  // liveness decides whether the node is gone
      continue;
    }
    p.tries++;
    p.next_at = now_ + RETRY_MS;
    radioSend(p.mac, p.data, p.len);
    i++;
  }
}

void Hub::dropPending(const Mac& mac) {
  pending_.erase(
      std::remove_if(pending_.begin(), pending_.end(), [&](const PendingCmd& p) { return p.mac == mac; }),
      pending_.end());
}

void Hub::sendWelcome(const Mac& mac, uint8_t slot, bool accepted) {
  proto::Welcome w{slot, static_cast<uint8_t>(accepted), settings_.channel, settings_.hb_interval_s,
                   static_cast<uint8_t>(sys_mode_)};
  uint8_t buf[proto::MAX_FRAME];
  size_t n = proto::encode(buf, header(Msg::Welcome, slot), w);
  radioSend(mac, buf, n);
}

void Hub::sendSetMode(NodeRec& n) {
  proto::SetMode m{static_cast<uint8_t>(sys_mode_)};
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encode(buf, header(Msg::SetMode, n.slot), m);
  sendReliable(n, buf, len);
}

void Hub::sendConfig(NodeRec& n) {
  proto::Config c{};
  auto put = [&](proto::Key k, uint16_t v) { c.items[c.count++] = proto::ConfigItem{static_cast<uint8_t>(k), v}; };
  put(proto::Key::Brightness, settings_.brightness);
  put(proto::Key::DebounceMs, n.cfg.debounce_ms);
  put(proto::Key::GlitchEdges, n.cfg.glitch_edges);
  put(proto::Key::GlitchWindowMs, n.cfg.glitch_window_ms);
  put(proto::Key::BattScaleUv, n.cfg.batt_scale_uv);
  put(proto::Key::HbIntervalS, settings_.hb_interval_s);
  put(proto::Key::HitFlash, n.cfg.hit_flash);
  put(proto::Key::LedPin, n.cfg.led_pin);
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encode(buf, header(Msg::Config, n.slot), c, proto::configLen(c));
  sendReliable(n, buf, len);
}

void Hub::sendAck(NodeRec& n, Msg type, uint16_t seq) {
  proto::Ack a{static_cast<uint8_t>(type), seq, 0, 0};
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encode(buf, header(Msg::HubAck, n.slot), a);
  radioSend(n.mac, buf, len);
}

void Hub::onSendResult(const Mac& mac, bool ok) {
  ok ? stats_.tx_ok++ : stats_.tx_fail++;
  NodeRec* n = reg_.byMac(mac);
  if (!n) return;
  if (ok) {
    n->send_fails = 0;
  } else if (++n->send_fails >= SEND_FAILS_OFFLINE && n->online) {
    // A missing MAC-layer ACK: drop it now instead of after the heartbeat
    // timeout. If it is alive after all, its next heartbeat brings it back.
    nodeOffline(*n, "not answering");
  }
}

// ================================================================ frames

void Hub::onFrame(const Mac& mac, const uint8_t* data, size_t len, int8_t rssi) {
  Header h;
  if (!proto::parseHeader(data, len, h) || !proto::isNodeToHub(h.type)) return;
  if (h.system_id != 0 && h.system_id != settings_.system_id) {
    stats_.rx_other_system++;
    return;  // another hub's target
  }

  NodeRec* n = reg_.byMac(mac);
  if (n) {
    if (n->has_seq && h.seq == n->last_seq && now_ - n->last_seq_at < 2000) {
      n->last_seen = now_;  // a retry of a frame we already handled
      stats_.rx_dup++;
      return;
    }
    n->has_seq = true;
    n->last_seq = h.seq;
    n->last_seq_at = now_;
  }

  switch (static_cast<Msg>(h.type)) {
    case Msg::Hello: {
      stats_.rx_hello++;
      proto::Hello p;
      if (proto::parsePayload(data, len, p)) handleHello(mac, h, p, rssi);
      break;
    }
    case Msg::Heartbeat: {
      stats_.rx_heartbeat++;
      proto::Heartbeat p;
      if (proto::parsePayload(data, len, p, proto::HEARTBEAT_MIN)) handleHeartbeat(mac, h, p, rssi);
      break;
    }
    case Msg::Hit: {
      stats_.rx_hit++;
      proto::Hit p;
      if (n && proto::parsePayload(data, len, p)) {
        seen(*n, rssi);
        handleHit(*n, p);
      }
      break;
    }
    case Msg::Ack: {
      stats_.rx_ack++;
      proto::Ack p;
      if (n && proto::parsePayload(data, len, p)) {
        seen(*n, rssi);
        handleAck(*n, p);
      }
      break;
    }
    default:
      break;
  }
}

NodeRec* Hub::admit(const Mac& mac) {
  uint8_t slot = reg_.freeSlot(settings_.max_nodes);
  if (!slot) {
    toast("warn", "Target limit reached (" + std::to_string(settings_.max_nodes) +
                      "). Remove one or raise the limit in Settings.");
    return nullptr;
  }
  reg_.dropPending(mac);
  NodeRec& n = reg_.add(mac, slot, mac.isVirtual());
  saveNodes();
  if (!n.virt) toast("info", "Target " + std::to_string(slot) + " added");
  nodes_dirty_ = true;
  return reg_.byMac(mac);
}

void Hub::handleHello(const Mac& mac, const Header& h, const proto::Hello& p, int8_t rssi) {
  (void)h;
  NodeRec* n = reg_.byMac(mac);
  if (!n) {
    if (settings_.auto_accept || mac.isVirtual()) n = admit(mac);
    if (!n) {
      bool fresh = true;
      for (auto& q : reg_.pending) fresh &= q.mac != mac;
      PendingNode& q = reg_.touchPending(mac, now_);
      memcpy(q.fw, &p.fw_major, 3);
      q.batt_mv = p.battery_mv;
      q.batt_pct = p.batt_pct;
      sendWelcome(mac, 0, false);
      if (fresh) {
        nodes_dirty_ = true;
        toast("info", "New target found. Tap Add on the Targets screen.");
      }
      return;
    }
  }
  n->fw[0] = p.fw_major;
  n->fw[1] = p.fw_minor;
  n->fw[2] = p.fw_patch;
  n->caps = p.caps;
  n->batt_mv = p.battery_mv;
  n->batt_pct = p.batt_pct;
  n->flags = p.flags;
  // A hello from an online target means it restarted: whatever the game had
  // lit on it is gone, so let the game see it leave and come back
  if (n->online && game_) nodeOffline(*n, "restarted");
  n->led = proto::Led{};
  seen(*n, rssi);
  sendWelcome(mac, n->slot, true);
  sendConfig(*n);
  nodes_dirty_ = true;
  if (ota_.active && ota_.phase == NodeOta::Phase::Reboot && ota_.idx < ota_.targets.size() &&
      ota_.targets[ota_.idx] == mac) {
    otaNextTarget(true);  // back after flashing
  }
}

void Hub::handleHeartbeat(const Mac& mac, const Header& h, const proto::Heartbeat& p, int8_t rssi) {
  NodeRec* n = reg_.byMac(mac);
  if (!n) {
    // A target paired with us that we no longer know (forgotten in the app)
    if (h.system_id == settings_.system_id) {
      reg_.touchPending(mac, now_);
      sendWelcome(mac, 0, false);
      nodes_dirty_ = true;
    }
    return;
  }
  if (n->batt_pct != p.batt_pct || n->flags != p.flags) nodes_dirty_ = true;
  n->batt_mv = p.battery_mv;
  n->batt_pct = p.batt_pct;
  n->flags = p.flags;
  n->mode = p.mode;
  n->uptime_s = p.uptime_s;
  if (p.fw_major && (n->fw[0] != p.fw_major || n->fw[1] != p.fw_minor || n->fw[2] != p.fw_patch)) {
    n->fw[0] = p.fw_major;  // known even if the hub restarted after the node's hello
    n->fw[1] = p.fw_minor;
    n->fw[2] = p.fw_patch;
    nodes_dirty_ = true;
  }
  seen(*n, rssi);
  sendAck(*n, Msg::Heartbeat, h.seq);
  if (p.mode != static_cast<uint8_t>(sys_mode_)) {
    bool waiting = false;
    for (auto& c : pending_) waiting |= c.mac == mac && c.type == static_cast<uint8_t>(Msg::SetMode);
    if (!waiting) sendSetMode(*n);
  }
}

void Hub::handleHit(NodeRec& n, const proto::Hit& p) {
  n.hits++;
  if (sys_mode_ == Mode::Calibrate) {
    JsonDocument d;
    d["t"] = "sensor";
    d["slot"] = n.slot;
    d["edges"] = p.edges;
    d["hits"] = n.hits;
    emit(d);
    return;
  }
  if (game_ && sys_mode_ == Mode::Active) {
    game_->onHit(n.slot, p.reaction_ms);
    processFinish();
    return;
  }
  // Outside a game: lets the app highlight the target that was hit
  JsonDocument d;
  d["t"] = "tap";
  d["slot"] = n.slot;
  emit(d);
}

void Hub::handleAck(NodeRec& n, const proto::Ack& p) {
  pending_.erase(std::remove_if(pending_.begin(), pending_.end(),
                                [&](const PendingCmd& c) {
                                  return c.mac == n.mac && c.type == p.acked_type && c.seq == p.acked_seq;
                                }),
                 pending_.end());
  if (ota_.active) otaOnAck(n, p);
}

void Hub::seen(NodeRec& n, int8_t rssi) {
  n.last_seen = now_;
  if (rssi) n.rssi = rssi;
  n.send_fails = 0;
  if (!n.online) nodeOnline(n);
}

void Hub::nodeOnline(NodeRec& n) {
  n.online = true;
  if (!n.virt) radio_.addPeer(n.mac);
  n.led = proto::Led{};
  rebuildSlots();
  nodes_dirty_ = true;
  leds_dirty_ = true;
  if (!n.virt) toast("info", "Target " + std::to_string(n.slot) + " online");
  if (game_) game_->onNodeFound(n.slot);
}

void Hub::nodeOffline(NodeRec& n, const char* why) {
  n.online = false;
  if (!n.virt) radio_.removePeer(n.mac);
  dropPending(n.mac);
  rebuildSlots();
  nodes_dirty_ = true;
  char line[64];
  snprintf(line, sizeof(line), "target %u offline (%s)", n.slot, why);
  log_.line(line);
  if (!n.virt) toast("warn", "Target " + std::to_string(n.slot) + " offline");
  if (game_) {
    game_->onNodeLost(n.slot);
    processFinish();
  }
}

void Hub::checkLiveness() {
  const uint32_t timeout = settings_.hb_interval_s * 3000UL + 1500;
  for (auto& n : reg_.nodes) {
    if (n.online && now_ - n.last_seen > timeout) nodeOffline(n, "no heartbeat");
  }
  size_t before = reg_.pending.size();
  reg_.expirePending(now_, PENDING_EXPIRE_MS);
  if (reg_.pending.size() != before) nodes_dirty_ = true;
}

void Hub::rebuildSlots() {
  slots_ = reg_.onlineSlots();
}

void Hub::saveNodes() { reg_.save(fs_); }

void Hub::syncVirtualNodes() {
  vnodes_.resize(settings_.virtual_nodes, now_);
  // Drop records of simulated targets that no longer exist
  for (size_t i = 0; i < reg_.nodes.size();) {
    NodeRec& n = reg_.nodes[i];
    if (n.virt && n.mac.b[5] > settings_.virtual_nodes) {
      if (n.online) nodeOffline(n, "simulation off");
      reg_.remove(reg_.nodes[i].mac);
      nodes_dirty_ = true;
      continue;
    }
    i++;
  }
  rebuildSlots();
}

// ================================================================ tick

void Hub::tick(uint32_t now) {
  now_ = now;

  if (vnodes_.count()) {
    vnodes_.tick(now, settings_.virtual_autoshoot, game_ ? game_->nextExpected() : 0);
    std::vector<OutFrame> frames;
    frames.swap(vnodes_.outbox());
    for (auto& f : frames) onFrame(f.from, f.data, f.len, -40);
  }

  retryPending();

  if (now - last_liveness_ >= 250) {
    last_liveness_ = now;
    checkLiveness();
  }

  if (idle_at_ && static_cast<int32_t>(now - idle_at_) >= 0 && !game_) {
    idle_at_ = 0;
    setSystemMode(Mode::Idle);
  }

  if (game_) {
    game_->tick();
    processFinish();
  }

  refreshLeds();
  if (ota_.active) otaTick();
  flushEvents();
}

void Hub::refreshLeds() {
  if (sys_mode_ != Mode::Active) return;
  for (auto& n : reg_.nodes) {
    if (!n.online || !persistentEffect(n.led) || now_ - n.led_sent_at < LED_REFRESH_MS) continue;
    n.led_sent_at = now_;
    uint8_t buf[proto::MAX_FRAME];
    size_t len = proto::encode(buf, header(Msg::Led, n.slot), n.led);  // same effect_id: no restart
    radioSend(n.mac, buf, len);
  }
}

bool Hub::wifiApplyDue(uint32_t now) {
  if (!wifi_apply_at_ || static_cast<int32_t>(now - wifi_apply_at_) < 0) return false;
  wifi_apply_at_ = 0;
  return true;
}

// ================================================================ GameHost

void Hub::led(uint8_t slot, const LedCmd& cmd) {
  NodeRec* n = reg_.bySlot(slot);
  if (!n || !n->online) return;
  proto::Led l{static_cast<uint8_t>(cmd.effect), cmd.r, cmd.g, cmd.b, cmd.p1, cmd.p2, 0};
  uint8_t id = n->led.effect_id;
  l.effect_id = static_cast<uint8_t>(id % 255 + 1);  // 1..255, new per effect
  n->led = l;
  n->led_sent_at = now_;
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encode(buf, header(Msg::Led, slot), l);
  radioSend(n->mac, buf, len);
  leds_dirty_ = true;
}

void Hub::ledAll(const LedCmd& cmd) {
  for (uint8_t s : slots_) led(s, cmd);
}

void Hub::feed(uint8_t slot, int points, int rt_ms, const char* note) {
  char line[80];
  snprintf(line, sizeof(line), "hit target %u: %+d pts, %d ms %s", slot, points, rt_ms, note ? note : "");
  log_.line(line);
  JsonDocument d;
  d["t"] = "feed";
  d["slot"] = slot;
  d["pts"] = points;
  if (rt_ms >= 0) d["rt"] = rt_ms;
  if (note && *note) d["note"] = note;
  emit(d);
}

uint32_t Hub::random(uint32_t n) {
  rng_ ^= rng_ << 13;
  rng_ ^= rng_ >> 17;
  rng_ ^= rng_ << 5;
  return n ? rng_ % n : 0;
}

void Hub::finish(bool save) {
  finish_pending_ = true;
  finish_save_ = save;
}

void Hub::processFinish() {
  if (!finish_pending_) return;
  finish_pending_ = false;
  endGame(true, finish_save_);
}

// ================================================================ game

void Hub::setSystemMode(Mode m) {
  sys_mode_ = m;
  for (auto& n : reg_.nodes) {
    n.led = proto::Led{};
    if (n.online) sendSetMode(n);
  }
  leds_dirty_ = true;
  nodes_dirty_ = true;
}

ApiResult Hub::startGame(const std::string& mode, JsonObjectConst cfg, int player, bool force) {
  if (safe_mode_) return ApiResult::err(503, "Safe mode: games are off until the hub restarts normally");
  if (ota_.active) return ApiResult::err(409, "A firmware update is running");
  const ModeInfo* info = findMode(mode);
  if (!info) return ApiResult::err(400, "Unknown game mode " + mode);
  if (slots_.size() < info->min_nodes) {
    return ApiResult::err(409, "This mode needs at least " + std::to_string(info->min_nodes) +
                                   " targets online (" + std::to_string(slots_.size()) + " now)");
  }
  if (player && !records_.player(player)) return ApiResult::err(400, "Unknown player");
  if (!force) {
    for (auto& n : reg_.nodes) {
      if (n.online && !n.virt && n.batt_pct != proto::BATT_UNKNOWN && n.batt_pct < 10) {
        ApiResult r = ApiResult::err(409, "Target " + std::to_string(n.slot) + " battery is at " +
                                              std::to_string(n.batt_pct) + "%. Start anyway?");
        r.confirm = "low_battery";
        return r;
      }
    }
  }
  GameMode* g = info->create(*this);
  std::string err;
  if (!g->configure(cfg, err)) {
    delete g;
    return ApiResult::err(400, err);
  }
  if (game_) endGame(false, false);
  game_ = g;
  game_mode_ = mode;
  game_player_ = player;
  idle_at_ = 0;
  last_result_.clear();
  setSystemMode(Mode::Active);
  game_->start();
  processFinish();
  JsonDocument d;
  d["t"] = "game";
  gameJson(d["game"].to<JsonObject>());
  emit(d);
  hud_dirty_ = true;
  return ApiResult::ok("Started");
}

ApiResult Hub::stopGame() {
  if (!game_) return ApiResult::err(409, "No game running");
  endGame(false, false);
  toast("info", "Game stopped");
  return ApiResult::ok("Stopped");
}

void Hub::endGame(bool natural, bool save) {
  if (!game_) return;
  if (!natural) game_->stop();
  if (natural) {
    JsonDocument r;
    r["t"] = "result";
    JsonObject res = r["result"].to<JsonObject>();
    res["mode"] = game_mode_;
    res["label"] = game_->label();
    res["score"] = game_->score();
    const Player* p = records_.player(game_player_);
    if (p) {
      res["player"] = p->id;
      res["player_name"] = p->name;
    }
    game_->result(res["stats"].to<JsonObject>());
    bool saved = save && game_->saveable();
    int rank = 0;
    if (saved) {
      JsonDocument e;
      e["s"] = game_->score();
      e["p"] = game_player_;
      e["n"] = p ? p->name.c_str() : "Guest";
      e["d"] = epochNow();
      e["l"] = game_->label();
      for (JsonPair kv : res["stats"].as<JsonObject>()) e[kv.key()] = kv.value();
      rank = records_.addScore(game_mode_, e.as<JsonObjectConst>());
    }
    res["saved"] = saved;
    res["rank"] = rank;
    char line[96];
    snprintf(line, sizeof(line), "game over: %s score %ld, %s (rank %d)", game_mode_.c_str(), game_->score(),
             saved ? "saved" : "not saved", rank);
    log_.line(line);
    last_result_.clear();
    serializeJson(res, last_result_);
    emit(r);
  }
  delete game_;
  game_ = nullptr;
  setSystemMode(Mode::Standby);
  idle_at_ = now_ + IDLE_AFTER_GAME_MS;
  JsonDocument d;
  d["t"] = "game";
  gameJson(d["game"].to<JsonObject>());
  emit(d);
}

void Hub::gameJson(JsonObject o) {
  o["running"] = game_ != nullptr;
  if (!game_) return;
  o["mode"] = game_mode_;
  o["label"] = game_->label();
  const Player* p = records_.player(game_player_);
  if (p) {
    o["player"] = p->id;
    o["player_name"] = p->name;
  }
  game_->hud(o["hud"].to<JsonObject>());
}

ApiResult Hub::setSensorTest(bool on) {
  if (game_) return ApiResult::err(409, "Stop the game first");
  if (on == (sys_mode_ == Mode::Calibrate)) return ApiResult::ok();
  idle_at_ = 0;
  setSystemMode(on ? Mode::Calibrate : Mode::Idle);
  return ApiResult::ok(on ? "Sensor test on" : "Sensor test off");
}

// ================================================================ targets API

ApiResult Hub::acceptNode(const Mac& mac) {
  if (reg_.byMac(mac)) return ApiResult::ok("Already added");
  bool known = false;
  for (auto& p : reg_.pending) known |= p.mac == mac;
  if (!known) return ApiResult::err(404, "That target isn't waiting to be added");
  NodeRec* n = admit(mac);
  if (!n) return ApiResult::err(409, "Target limit reached");
  sendWelcome(mac, n->slot, true);  // it links on this; its next hello/heartbeat brings it online
  return ApiResult::ok("Added as target " + std::to_string(n->slot));
}

ApiResult Hub::forgetNode(const Mac& mac) {
  NodeRec* n = reg_.byMac(mac);
  if (!n) {
    reg_.dropPending(mac);
    nodes_dirty_ = true;
    return ApiResult::ok("Removed");
  }
  if (n->virt) return ApiResult::err(400, "Simulated targets are set in Settings > Developer");
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encodeEmpty(buf, header(Msg::Forget, n->slot));
  radioSend(mac, buf, len);
  if (n->online) nodeOffline(*n, "forgotten");
  reg_.remove(mac);
  saveNodes();
  rebuildSlots();
  nodes_dirty_ = true;
  return ApiResult::ok("Target removed");
}

ApiResult Hub::updateNode(const Mac& mac, JsonObjectConst in) {
  NodeRec* n = reg_.byMac(mac);
  if (!n) return ApiResult::err(404, "Unknown target");
  if (in["name"].is<const char*>()) {
    std::string name = in["name"].as<const char*>();
    if (name.empty() || name.size() > 20) return ApiResult::err(400, "Name must be 1-20 characters");
    n->name = name;
  }
  if (!in["color"].isNull()) n->color = (in["color"] | 0) & 7;
  struct Range {
    const char* key;
    int lo, hi;
  };
  const Range ranges[] = {{"debounce_ms", 50, 2000}, {"glitch_edges", 1, 10}, {"glitch_window_ms", 5, 200}};
  JsonObjectConst c = in["cfg"];
  for (auto& r : ranges) {
    if (c[r.key].isNull()) continue;
    int v = c[r.key] | -1;
    if (v < r.lo || v > r.hi) {
      return ApiResult::err(400, std::string(r.key) + " must be " + std::to_string(r.lo) + "-" + std::to_string(r.hi));
    }
  }
  bool cfg_changed = !c.isNull();
  if (!c["debounce_ms"].isNull()) n->cfg.debounce_ms = c["debounce_ms"];
  if (!c["glitch_edges"].isNull()) n->cfg.glitch_edges = c["glitch_edges"];
  if (!c["glitch_window_ms"].isNull()) n->cfg.glitch_window_ms = c["glitch_window_ms"];
  if (c["hit_flash"].is<bool>()) n->cfg.hit_flash = c["hit_flash"];
  if (!c["led_pin"].isNull()) {
    int pin = c["led_pin"] | -1;
    if (pin != 0 && pin != 4) return ApiResult::err(400, "LED pin must be 0 (D3) or 4 (D2)");
    n->cfg.led_pin = pin;
  }
  if (!in["slot"].isNull()) {
    int slot = in["slot"] | 0;
    if (slot < 1 || slot > settings_.max_nodes) {
      return ApiResult::err(400, "Number must be 1-" + std::to_string(settings_.max_nodes));
    }
    if (game_) return ApiResult::err(409, "Stop the game before renumbering targets");
    NodeRec* other = reg_.moveTo(*n, static_cast<uint8_t>(slot));
    if (other) sendWelcome(other->mac, other->slot, true);
    n = reg_.byMac(mac);
    sendWelcome(mac, n->slot, true);
    rebuildSlots();
  }
  if (cfg_changed && n->online) sendConfig(*n);
  if (!n->virt) saveNodes();
  nodes_dirty_ = true;
  return ApiResult::ok("Saved");
}

ApiResult Hub::identifyNode(const Mac& mac) {
  NodeRec* n = reg_.byMac(mac);
  if (!n || !n->online) return ApiResult::err(409, "Target is offline");
  proto::Identify p{5};
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encode(buf, header(Msg::Identify, n->slot), p);
  sendReliable(*n, buf, len);
  return ApiResult::ok("Target " + std::to_string(n->slot) + " is blinking white");
}

ApiResult Hub::calibrateBattery(const Mac& mac, int measured_mv) {
  NodeRec* n = reg_.byMac(mac);
  if (!n || !n->online) return ApiResult::err(409, "Target is offline");
  if (measured_mv < 2800 || measured_mv > 4500) return ApiResult::err(400, "Enter the battery voltage, 2.80-4.50 V");
  if (n->batt_mv < 500) return ApiResult::err(409, "This target doesn't report a battery reading");
  uint32_t scale = static_cast<uint32_t>(n->cfg.batt_scale_uv) * measured_mv / n->batt_mv;
  if (scale < 1000 || scale > 20000) return ApiResult::err(400, "That reading is too far from what the target measures");
  n->cfg.batt_scale_uv = static_cast<uint16_t>(scale);
  n->batt_mv = static_cast<uint16_t>(measured_mv);
  sendConfig(*n);
  saveNodes();
  nodes_dirty_ = true;
  return ApiResult::ok("Battery calibrated");
}

ApiResult Hub::rebootNode(const Mac& mac) {
  NodeRec* n = reg_.byMac(mac);
  if (!n || !n->online) return ApiResult::err(409, "Target is offline");
  uint8_t buf[proto::MAX_FRAME];
  size_t len = proto::encodeEmpty(buf, header(Msg::Reboot, n->slot));
  sendReliable(*n, buf, len);
  return ApiResult::ok("Restarting target " + std::to_string(n->slot));
}

ApiResult Hub::simHit(const Mac& mac) {
  if (!mac.isVirtual()) return ApiResult::err(400, "Only simulated targets can be hit from the app");
  vnodes_.hit(mac, now_);
  return ApiResult::ok();
}

ApiResult Hub::updateSettings(JsonObjectConst in) {
  Settings before = settings_;
  std::string err;
  if (!settings_.update(in, err)) return ApiResult::err(400, err);
  if (settings_.max_nodes < reg_.nodes.size() && settings_.max_nodes < before.max_nodes) {
    settings_ = before;
    return ApiResult::err(409, "Remove targets first: " + std::to_string(reg_.nodes.size()) + " are paired");
  }
  settings_.save(fs_);
  if (settings_.brightness != before.brightness || settings_.hb_interval_s != before.hb_interval_s) {
    for (auto& n : reg_.nodes)
      if (n.online) sendConfig(n);
  }
  if (settings_.virtual_nodes != before.virtual_nodes) syncVirtualNodes();
  if (settings_.channel != before.channel) {
    // Tell the targets first; they follow after the delay, then the AP moves
    proto::Channel c{settings_.channel, WIFI_APPLY_DELAY_MS};
    for (auto& n : reg_.nodes) {
      if (!n.online || n.virt) continue;
      uint8_t buf[proto::MAX_FRAME];
      size_t len = proto::encode(buf, header(Msg::Channel, n.slot), c);
      sendReliable(n, buf, len);
    }
  }
  if (Settings::wifiChanged(before, settings_)) {
    wifi_apply_at_ = now_ + WIFI_APPLY_DELAY_MS;
    toast("warn", "WiFi settings changed: reconnect your phone to \"" + settings_.name + "\"");
  }
  JsonDocument d;
  d["t"] = "settings";
  settings_.toJson(d["settings"].to<JsonObject>(), false);
  emit(d);
  return ApiResult::ok("Saved");
}

void Hub::setTime(uint64_t epoch_ms) {
  if (epoch_ms < 1700000000000ULL) return;  // not a real clock
  epoch_base_ = epoch_ms / 1000 - now_ / 1000;
}

uint32_t Hub::epochNow() const { return epoch_base_ ? static_cast<uint32_t>(epoch_base_ + now_ / 1000) : 0; }

void Hub::modesJson(std::string& out) const {
  out = "[";
  bool first = true;
  for (auto& m : gameModes()) {
    if (!first) out += ",";
    out += m.schema;
    first = false;
  }
  out += "]";
}

// ================================================================ node OTA

ApiResult Hub::startNodeOta(uint32_t size, const uint8_t md5[16], JsonArrayConst macs) {
  if (game_) return ApiResult::err(409, "Stop the game first");
  if (ota_.active) return ApiResult::err(409, "An update is already running");
  if (!size || fs_.size(NODE_OTA_PATH) != size) return ApiResult::err(400, "Upload the target firmware first");
  NodeOta job;
  for (JsonVariantConst v : macs) {
    Mac m;
    NodeRec* n = Mac::parse(v | "", m) ? reg_.byMac(m) : nullptr;
    if (!n || !n->online || n->virt) continue;
    if (!(n->caps & proto::CAP_OTA)) continue;
    job.targets.push_back(m);
  }
  if (job.targets.empty()) return ApiResult::err(409, "No online target can be updated");
  job.active = true;
  job.size = size;
  memcpy(job.md5, md5, 16);
  ota_ = job;
  idle_at_ = 0;
  emitOta(true);  // otaTick() sends OtaBegin to the first target
  return ApiResult::ok("Updating " + std::to_string(ota_.targets.size()) + " target(s)");
}

void Hub::otaNextTarget(bool ok) {
  (ok ? ota_.done : ota_.failed).push_back(ota_.targets[ota_.idx].str());
  ota_.idx++;
  ota_.phase = NodeOta::Phase::Begin;
  ota_.offset = 0;
  ota_.tries = 0;
  ota_.waiting = false;
  if (ota_.idx >= ota_.targets.size()) {
    ota_.active = false;
    emitOta(true);
    toast(ota_.failed.empty() ? "info" : "warn",
          "Target update finished: " + std::to_string(ota_.done.size()) + " updated, " +
              std::to_string(ota_.failed.size()) + " failed");
    return;
  }
  emitOta(true);
}

void Hub::otaSend(NodeRec& n) {
  uint8_t buf[proto::MAX_FRAME];
  size_t len = 0;
  Header h;
  switch (ota_.phase) {
    case NodeOta::Phase::Begin: {
      proto::OtaBegin b{};
      b.size = ota_.size;
      memcpy(b.md5, ota_.md5, 16);
      h = header(Msg::OtaBegin, n.slot);
      len = proto::encode(buf, h, b);
      break;
    }
    case NodeOta::Phase::Data: {
      proto::OtaData d{};
      d.offset = ota_.offset;
      uint32_t left = ota_.size - ota_.offset;
      d.len = static_cast<uint8_t>(left < proto::OTA_CHUNK ? left : proto::OTA_CHUNK);
      if (!fs_.readAt(NODE_OTA_PATH, d.offset, d.data, d.len)) {
        otaNextTarget(false);
        return;
      }
      h = header(Msg::OtaData, n.slot);
      len = proto::encode(buf, h, d, proto::otaDataLen(d));
      break;
    }
    case NodeOta::Phase::End:
      h = header(Msg::OtaEnd, n.slot);
      len = proto::encodeEmpty(buf, h);
      break;
    case NodeOta::Phase::Reboot:
      return;
  }
  ota_.wait_type = h.type;
  ota_.wait_seq = h.seq;
  ota_.sent_at = now_;
  ota_.waiting = true;
  radioSend(n.mac, buf, len);
}

void Hub::otaTick() {
  NodeRec* n = reg_.byMac(ota_.targets[ota_.idx]);
  if (ota_.phase == NodeOta::Phase::Reboot) {
    if (now_ - ota_.sent_at > 30000) otaNextTarget(false);  // flashed but never came back
    return;
  }
  if (!n || !n->online) {
    otaNextTarget(false);
    return;
  }
  if (!ota_.waiting) {
    otaSend(*n);
  } else if (now_ - ota_.sent_at > 400) {
    if (++ota_.tries > 10) {
      otaNextTarget(false);
      return;
    }
    otaSend(*n);
  }
  emitOta(false);
}

void Hub::otaOnAck(NodeRec& n, const proto::Ack& a) {
  if (ota_.idx >= ota_.targets.size() || n.mac != ota_.targets[ota_.idx]) return;
  if (!ota_.waiting || a.acked_type != ota_.wait_type || a.acked_seq != ota_.wait_seq) return;
  ota_.waiting = false;
  ota_.tries = 0;
  auto status = static_cast<proto::AckStatus>(a.status);
  switch (ota_.phase) {
    case NodeOta::Phase::Begin:
      if (status != proto::AckStatus::Ok) {
        otaNextTarget(false);
        return;
      }
      ota_.phase = NodeOta::Phase::Data;
      ota_.offset = 0;
      break;
    case NodeOta::Phase::Data:
      if (status == proto::AckStatus::Ok || status == proto::AckStatus::BadOffset) {
        ota_.offset = a.value;  // the node says where to continue
        if (ota_.offset >= ota_.size) ota_.phase = NodeOta::Phase::End;
      } else {
        otaNextTarget(false);
      }
      break;
    case NodeOta::Phase::End:
      if (status != proto::AckStatus::Ok) {
        otaNextTarget(false);
        return;
      }
      ota_.phase = NodeOta::Phase::Reboot;
      ota_.sent_at = now_;
      break;
    case NodeOta::Phase::Reboot:
      break;
  }
}

void Hub::otaJson(JsonObject o) {
  o["active"] = ota_.active;
  o["total"] = ota_.targets.size();
  if (ota_.active && ota_.idx < ota_.targets.size()) {
    NodeRec* n = reg_.byMac(ota_.targets[ota_.idx]);
    o["slot"] = n ? n->slot : 0;
    const char* phases[] = {"starting", "sending", "verifying", "restarting"};
    o["phase"] = phases[static_cast<int>(ota_.phase)];
    o["pct"] = ota_.size ? static_cast<int>(100ULL * ota_.offset / ota_.size) : 0;
  }
  JsonArray d = o["done"].to<JsonArray>();
  for (auto& m : ota_.done) d.add(m);
  JsonArray f = o["failed"].to<JsonArray>();
  for (auto& m : ota_.failed) f.add(m);
}

void Hub::emitOta(bool force) {
  if (!force && now_ - ota_.last_emit < 500) return;
  ota_.last_emit = now_;
  JsonDocument d;
  d["t"] = "ota";
  otaJson(d["ota"].to<JsonObject>());
  emit(d);
}

// ================================================================ events

void Hub::emit(JsonDocument& doc) {
  if (!events_.clients()) return;
  std::string s;
  serializeJson(doc, s);
  events_.emit(s);
}

void Hub::toast(const char* level, const std::string& msg) {
  JsonDocument d;
  d["t"] = "toast";
  d["level"] = level;
  d["msg"] = msg;
  emit(d);
  log_.line(msg.c_str());
}

void Hub::nodesJson(JsonObject o) {
  JsonArray arr = o["nodes"].to<JsonArray>();
  for (auto& n : reg_.nodes) n.toJson(arr.add<JsonObject>());
  JsonArray p = o["pending"].to<JsonArray>();
  for (auto& q : reg_.pending) q.toJson(p.add<JsonObject>(), now_);
}

void Hub::emitNodes() {
  JsonDocument d;
  JsonObject o = d.to<JsonObject>();
  o["t"] = "nodes";
  nodesJson(o);
  emit(d);
}

void Hub::flushEvents() {
  if (nodes_dirty_) {
    nodes_dirty_ = false;
    leds_dirty_ = false;  // the node list carries the LEDs too
    emitNodes();
  }
  if (leds_dirty_) {
    leds_dirty_ = false;
    JsonDocument d;
    d["t"] = "leds";
    JsonArray v = d["v"].to<JsonArray>();
    for (auto& n : reg_.nodes) {
      JsonArray a = v.add<JsonArray>();
      a.add(n.slot);
      a.add(n.led.effect);
      char rgb[8];
      snprintf(rgb, sizeof(rgb), "#%02x%02x%02x", n.led.r, n.led.g, n.led.b);
      a.add(rgb);
    }
    emit(d);
  }
  if (hud_dirty_ && game_) {
    hud_dirty_ = false;
    JsonDocument d;
    d["t"] = "hud";
    game_->hud(d["hud"].to<JsonObject>());
    emit(d);
  }
}

void Hub::stateJson(JsonObject o) {
  o["t"] = "state";
  o["fw"] = TARGETS_FW_VERSION;
  o["uptime_s"] = now_ / 1000;
  o["time_set"] = epoch_base_ != 0;
  o["safe_mode"] = safe_mode_;
  o["mode"] = modeName(sys_mode_);
  settings_.toJson(o["settings"].to<JsonObject>(), false);
  nodesJson(o);
  gameJson(o["game"].to<JsonObject>());
  if (!last_result_.empty()) o["last_result"] = serialized(last_result_);
  otaJson(o["ota"].to<JsonObject>());
}
