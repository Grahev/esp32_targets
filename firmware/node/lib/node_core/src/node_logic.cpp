#include "node_logic.h"

#include <string.h>

using proto::Effect;
using proto::Header;
using proto::Mode;
using proto::Msg;

namespace {

Rgb breathe(Rgb c, uint32_t period, uint32_t now) {
  uint32_t phase = (now % period) * 510 / period;
  uint32_t tri = phase <= 255 ? phase : 510 - phase;
  return scale(c, static_cast<uint8_t>(tri * tri / 255));
}

Rgb blink(Rgb c, uint32_t period, uint32_t now) { return (now % period) < period / 2 ? c : Rgb{0, 0, 0}; }

const Rgb WHITE{255, 255, 255};

}  // namespace

NodeLogic::NodeLogic(NodeIo& io, NodeConfig& cfg, const NodeInfo& info) : io_(io), cfg_(cfg), info_(info) {}

void NodeLogic::begin(uint32_t now) {
  now_ = now;
  boot_ms_ = now;
  filter_.configure(cfg_.debounce_ms, cfg_.glitch_edges, cfg_.glitch_window_ms);
  channel_ = (cfg_.channel >= 1 && cfg_.channel <= 13) ? cfg_.channel : 1;
  io_.setChannel(channel_);
  // Even with a stored hub, start by saying hello on its channel: the hub
  // answers within one hello period and tells us the current mode.
  enterSearching(now);
}

// ---------------------------------------------------------------- sending

Header NodeLogic::header(Msg type) {
  uint16_t sid = cfg_.system_id;
  if (state_ == LinkState::Pairing) {
    sid = 0;  // the hub we are pairing with may not be the one we remember
  } else if (state_ == LinkState::Searching && now_ - search_started_ >= FORGET_SYSTEM_AFTER_MS) {
    sid = 0;  // our hub is gone for good (e.g. factory reset): let any hub see us as new
  }
  return proto::makeHeader(type, sid, cfg_.node_id, ++seq_);
}

void NodeLogic::enqueue(const uint8_t* data, size_t len, bool unicast) {
  if (q_count_ == QUEUE_LEN) {
    io_.log("send queue full, dropping oldest");
    if (inflight_) return;  // the front is on air; drop the new frame instead
    popFront();
  }
  Frame& f = queue_[(q_head_ + q_count_) % QUEUE_LEN];
  memcpy(f.data, data, len);
  f.len = static_cast<uint8_t>(len);
  f.unicast = unicast;
  f.attempts = 0;
  q_count_++;
}

void NodeLogic::popFront() {
  if (!q_count_) return;
  q_head_ = (q_head_ + 1) % QUEUE_LEN;
  q_count_--;
}

void NodeLogic::clearQueue() {
  q_head_ = 0;
  q_count_ = 0;
  // inflight_ is left alone: its onSendDone() still arrives and is ignored
}

void NodeLogic::pumpQueue(uint32_t now) {
  if (inflight_ && now - inflight_at_ > SEND_DONE_TIMEOUT_MS) {
    onSendDone(false, now);  // the radio never reported back
  }
  if (inflight_ || !q_count_) return;
  Frame& f = queue_[q_head_];
  const uint8_t* mac = f.unicast ? cfg_.hub_mac : nullptr;
  if (f.unicast && !cfg_.has_hub) {
    popFront();
    return;
  }
  if (io_.send(mac, f.data, f.len)) {
    inflight_ = true;
    inflight_at_ = now;
    return;
  }
  if (++f.attempts >= SEND_ATTEMPTS) {
    popFront();
    if (f.unicast) fail_streak_++;
  }
}

void NodeLogic::onSendDone(bool ok, uint32_t now) {
  now_ = now;
  if (!inflight_) return;
  inflight_ = false;
  if (!q_count_) return;  // queue was cleared while on air
  Frame& f = queue_[q_head_];
  if (ok || !f.unicast) {
    if (f.unicast) fail_streak_ = 0;
    popFront();
    return;
  }
  if (++f.attempts < SEND_ATTEMPTS) return;  // retried on the next pump
  popFront();
  if (++fail_streak_ >= MAX_FAIL_STREAK && state_ != LinkState::Searching) {
    io_.log("hub not answering (radio), searching");
    enterSearching(now);
  }
}

void NodeLogic::sendHello() {
  proto::Hello p{};
  p.fw_major = info_.fw_major;
  p.fw_minor = info_.fw_minor;
  p.fw_patch = info_.fw_patch;
  p.hw_rev = info_.hw_rev;
  p.caps = info_.caps;
  p.led_pin = cfg_.led_pin;
  p.battery_mv = batt_mv_;
  p.batt_pct = batt_pct_;
  p.flags = batt_flags_;
  uint8_t buf[proto::MAX_FRAME];
  size_t n = proto::encode(buf, header(Msg::Hello), p);
  enqueue(buf, n, state_ == LinkState::Pairing);
}

void NodeLogic::sendHeartbeat() {
  proto::Heartbeat p{};
  p.battery_mv = batt_mv_;
  p.batt_pct = batt_pct_;
  p.flags = batt_flags_ | (effect_.lit(now_) ? proto::FLAG_LIT : 0);
  p.mode = static_cast<uint8_t>(mode_);
  p.effect_id = effect_.id();
  p.uptime_s = (now_ - boot_ms_) / 1000;
  p.fw_major = info_.fw_major;
  p.fw_minor = info_.fw_minor;
  p.fw_patch = info_.fw_patch;
  uint8_t buf[proto::MAX_FRAME];
  size_t n = proto::encode(buf, header(Msg::Heartbeat), p);
  enqueue(buf, n, true);
}

void NodeLogic::sendAck(Msg type, uint16_t seq, proto::AckStatus status, uint32_t value) {
  proto::Ack p{};
  p.acked_type = static_cast<uint8_t>(type);
  p.acked_seq = seq;
  p.status = static_cast<uint8_t>(status);
  p.value = value;
  uint8_t buf[proto::MAX_FRAME];
  size_t n = proto::encode(buf, header(Msg::Ack), p);
  enqueue(buf, n, true);
}

// ---------------------------------------------------------------- state

void NodeLogic::enterSearching(uint32_t now) {
  state_ = LinkState::Searching;
  search_started_ = now;
  next_hello_ = now;
  hellos_on_channel_ = 0;
  missed_heartbeats_ = 0;
  fail_streak_ = 0;
  clearQueue();
  mode_ = Mode::Idle;
  effect_ = EffectPlayer{};
}

void NodeLogic::tick(uint32_t now) {
  now_ = now;
  filter_.poll(now);

  if (reboot_pending_ && static_cast<int32_t>(now - reboot_at_) >= 0) {
    io_.reboot();
    reboot_pending_ = false;
  }
  if (channel_switch_pending_ && static_cast<int32_t>(now - channel_switch_at_) >= 0) {
    channel_switch_pending_ = false;
    channel_ = channel_switch_to_;
    cfg_.channel = channel_;
    io_.setChannel(channel_);
    io_.saveConfig(cfg_);
  }
  if (ota_active_ && now - ota_last_ > OTA_IDLE_TIMEOUT_MS) {
    io_.log("OTA stalled, aborting");
    io_.otaAbort();
    otaReset();
  }

  switch (state_) {
    case LinkState::Searching:
      if (static_cast<int32_t>(now - next_hello_) >= 0) {
        if (hellos_on_channel_ >= HELLOS_PER_CHANNEL) {
          channel_ = channel_ % 13 + 1;
          io_.setChannel(channel_);
          hellos_on_channel_ = 0;
        }
        sendHello();
        hellos_on_channel_++;
        next_hello_ = now + HELLO_MS;
      }
      break;
    case LinkState::Pairing:
      if (static_cast<int32_t>(now - next_hello_) >= 0) {
        if (missed_heartbeats_ >= MAX_MISSED_HEARTBEATS) {
          enterSearching(now);
          break;
        }
        sendHello();
        missed_heartbeats_++;
        next_hello_ = now + PAIRING_HELLO_MS;
      }
      break;
    case LinkState::Linked:
      if (static_cast<int32_t>(now - next_heartbeat_) >= 0) {
        if (missed_heartbeats_ >= MAX_MISSED_HEARTBEATS) {
          io_.log("hub stopped answering heartbeats, searching");
          enterSearching(now);
          break;
        }
        sendHeartbeat();
        missed_heartbeats_++;
        next_heartbeat_ = now + (cfg_.hb_interval_s ? cfg_.hb_interval_s : 2) * 1000UL;
      }
      break;
  }
  pumpQueue(now);
}

void NodeLogic::onFrame(const uint8_t* mac, const uint8_t* data, size_t len, uint32_t now) {
  now_ = now;
  Header h;
  if (!proto::parseHeader(data, len, h)) return;
  if (proto::isNodeToHub(h.type)) return;  // another node's broadcast

  if (h.type == static_cast<uint8_t>(Msg::Welcome)) {
    proto::Welcome w;
    if (proto::parsePayload(data, len, w)) onWelcome(mac, h, w, now);
    return;
  }
  if (state_ == LinkState::Searching || !cfg_.has_hub) return;
  if (memcmp(mac, cfg_.hub_mac, 6) != 0) return;
  if (state_ == LinkState::Linked && h.system_id != cfg_.system_id) return;
  onHubFrame(h, data, len, now);
}

void NodeLogic::onWelcome(const uint8_t* mac, const Header& h, const proto::Welcome& w, uint32_t now) {
  bool searching_long = state_ == LinkState::Searching && now - search_started_ >= FORGET_SYSTEM_AFTER_MS;
  if (cfg_.system_id != 0 && h.system_id != cfg_.system_id && !searching_long) return;  // not our hub
  if (state_ == LinkState::Linked && memcmp(mac, cfg_.hub_mac, 6) != 0) return;

  missed_heartbeats_ = 0;
  fail_streak_ = 0;
  bool mac_changed = !cfg_.has_hub || memcmp(mac, cfg_.hub_mac, 6) != 0;
  memcpy(cfg_.hub_mac, mac, 6);
  cfg_.has_hub = true;

  if (!w.accepted) {
    if (state_ != LinkState::Pairing) {
      state_ = LinkState::Pairing;
      clearQueue();
      next_hello_ = now + PAIRING_HELLO_MS;
      io_.log("waiting to be added in the app");
    }
    return;
  }

  uint8_t hb = w.hb_interval_s ? w.hb_interval_s : 2;
  bool changed = mac_changed || cfg_.node_id != w.node_id || cfg_.system_id != h.system_id ||
                 cfg_.channel != w.channel || cfg_.hb_interval_s != hb;
  cfg_.node_id = w.node_id;
  cfg_.system_id = h.system_id;
  cfg_.channel = w.channel;
  cfg_.hb_interval_s = hb;
  if (changed) io_.saveConfig(cfg_);
  if (channel_ != w.channel) {
    channel_ = w.channel;
    io_.setChannel(channel_);
  }
  if (state_ != LinkState::Linked) {
    state_ = LinkState::Linked;
    clearQueue();
    io_.log("linked to hub");
  }
  setMode(static_cast<Mode>(w.mode), now);
  next_heartbeat_ = now + 200;  // report battery soon
}

void NodeLogic::onHubFrame(const Header& h, const uint8_t* data, size_t len, uint32_t now) {
  missed_heartbeats_ = 0;
  Msg type = static_cast<Msg>(h.type);
  switch (type) {
    case Msg::HubAck:
      break;  // heartbeat answered (missed_heartbeats_ was reset above)
    case Msg::SetMode: {
      proto::SetMode p;
      if (!proto::parsePayload(data, len, p)) return;
      setMode(static_cast<Mode>(p.mode), now);
      sendAck(type, h.seq, proto::AckStatus::Ok);
      break;
    }
    case Msg::Led: {
      proto::Led p;
      if (!proto::parsePayload(data, len, p)) return;
      if (mode_ == Mode::Active) effect_.apply(p, now);
      break;
    }
    case Msg::Config: {
      proto::Config p;
      if (!proto::parseConfig(data, len, p)) return;
      applyConfig(p);
      io_.saveConfig(cfg_);
      sendAck(type, h.seq, proto::AckStatus::Ok);
      break;
    }
    case Msg::Identify: {
      proto::Identify p;
      if (!proto::parsePayload(data, len, p)) return;
      identify_until_ = now + p.seconds * 1000UL;
      sendAck(type, h.seq, proto::AckStatus::Ok);
      break;
    }
    case Msg::Channel: {
      proto::Channel p;
      if (!proto::parsePayload(data, len, p) || p.channel < 1 || p.channel > 13) return;
      channel_switch_pending_ = true;
      channel_switch_to_ = p.channel;
      channel_switch_at_ = now + p.switch_in_ms;
      sendAck(type, h.seq, proto::AckStatus::Ok);
      break;
    }
    case Msg::OtaBegin: {
      proto::OtaBegin p;
      if (!proto::parsePayload(data, len, p)) return;
      if (ota_active_) io_.otaAbort();
      otaReset();
      if (!io_.otaBegin(p.size, p.md5)) {
        sendAck(type, h.seq, proto::AckStatus::NoSpace);
        return;
      }
      ota_active_ = true;
      ota_size_ = p.size;
      ota_last_ = now;
      sendAck(type, h.seq, proto::AckStatus::Ok, 0);
      break;
    }
    case Msg::OtaData: {
      proto::OtaData p;
      if (!proto::parseOtaData(data, len, p)) return;
      if (!ota_active_) {
        sendAck(type, h.seq, proto::AckStatus::Error);
        return;
      }
      ota_last_ = now;
      if (p.offset > ota_next_) {
        sendAck(type, h.seq, proto::AckStatus::BadOffset, ota_next_);
        return;
      }
      if (p.offset == ota_next_) {  // offset < next is a re-send: just re-ACK
        if (ota_next_ + p.len > ota_size_ || !io_.otaWrite(p.data, p.len)) {
          io_.otaAbort();
          otaReset();
          sendAck(type, h.seq, proto::AckStatus::Error);
          return;
        }
        ota_next_ += p.len;
      }
      sendAck(type, h.seq, proto::AckStatus::Ok, ota_next_);
      break;
    }
    case Msg::OtaEnd: {
      if (ota_active_ && ota_next_ == ota_size_ && io_.otaEnd()) {
        otaReset();
        sendAck(type, h.seq, proto::AckStatus::Ok, ota_size_);
        reboot_pending_ = true;
        reboot_at_ = now + 500;
      } else {
        if (ota_active_) io_.otaAbort();
        otaReset();
        sendAck(type, h.seq, proto::AckStatus::Md5Mismatch, ota_next_);
      }
      break;
    }
    case Msg::Reboot:
      sendAck(type, h.seq, proto::AckStatus::Ok);
      reboot_pending_ = true;
      reboot_at_ = now + 300;
      break;
    case Msg::Forget:
      cfg_.system_id = 0;
      cfg_.node_id = 0;
      cfg_.has_hub = false;
      io_.saveConfig(cfg_);
      enterSearching(now);
      break;
    default:
      break;
  }
}

void NodeLogic::applyConfig(const proto::Config& c) {
  for (uint8_t i = 0; i < c.count; i++) {
    uint16_t v = c.items[i].value;
    switch (static_cast<proto::Key>(c.items[i].key)) {
      case proto::Key::Brightness:
        cfg_.brightness = v > 255 ? 255 : static_cast<uint8_t>(v);
        break;
      case proto::Key::DebounceMs:
        cfg_.debounce_ms = v;
        break;
      case proto::Key::GlitchEdges:
        cfg_.glitch_edges = v < 1 ? 1 : (v > 10 ? 10 : static_cast<uint8_t>(v));
        break;
      case proto::Key::GlitchWindowMs:
        cfg_.glitch_window_ms = v;
        break;
      case proto::Key::BattScaleUv:
        if (v) cfg_.batt_scale_uv = v;
        break;
      case proto::Key::HbIntervalS:
        cfg_.hb_interval_s = v < 1 ? 1 : (v > 30 ? 30 : static_cast<uint8_t>(v));
        break;
      case proto::Key::HitFlash:
        cfg_.hit_flash = v != 0;
        break;
      case proto::Key::LedPin:
        if (v == 0 || v == 4) cfg_.led_pin = static_cast<uint8_t>(v);
        break;
    }
  }
  filter_.configure(cfg_.debounce_ms, cfg_.glitch_edges, cfg_.glitch_window_ms);
}

void NodeLogic::setMode(Mode m, uint32_t now) {
  (void)now;
  if (m == mode_) return;
  mode_ = m;
  effect_ = EffectPlayer{};
  flash_until_ = 0;
}

void NodeLogic::setBattery(uint16_t mv, uint8_t pct, uint8_t flags) {
  batt_mv_ = mv;
  batt_pct_ = pct;
  if (pct != proto::BATT_UNKNOWN && pct < 15) flags |= proto::FLAG_LOW_BATT;
  batt_flags_ = flags;
}

void NodeLogic::onEdge(uint32_t ms) {
  HitResult r = filter_.onEdge(ms);
  if (r.hit) handleHit(r);
}

void NodeLogic::handleHit(const HitResult& r) {
  hit_count_++;
  proto::Hit p{};
  p.reaction_ms = proto::RT_NONE;
  p.edges = r.edges;
  p.hit_count = hit_count_;
  p.uptime_ms = r.at_ms - boot_ms_;
  bool was_lit = mode_ == Mode::Active && effect_.lit(r.at_ms);
  if (was_lit) {
    int32_t rt = static_cast<int32_t>(r.at_ms - effect_.litAt());
    if (rt >= 0) p.reaction_ms = rt > 65534 ? 65534 : static_cast<uint16_t>(rt);
    p.effect_id = effect_.id();
  }

  // Local feedback right away, without waiting for the hub
  switch (mode_) {
    case Mode::Active:
      if (was_lit) effect_.clear(now_);
      if (cfg_.hit_flash) {
        flash_color_ = WHITE;
        flash_until_ = now_ + 80;
      }
      break;
    case Mode::Calibrate:
      flash_color_ = Rgb{0, 255, 0};
      flash_until_ = now_ + 150;
      break;
    default:
      flash_color_ = Rgb{0, 90, 90};
      flash_until_ = now_ + 60;
      break;
  }

  if (state_ != LinkState::Linked) return;
  uint8_t buf[proto::MAX_FRAME];
  size_t n = proto::encode(buf, header(Msg::Hit), p);
  enqueue(buf, n, true);
}

void NodeLogic::otaReset() {
  ota_active_ = false;
  ota_size_ = 0;
  ota_next_ = 0;
}

Rgb NodeLogic::led(uint32_t now) const {
  Rgb c{0, 0, 0};
  if (ota_active_) {
    c = breathe(Rgb{255, 0, 255}, 600, now);
  } else if (static_cast<int32_t>(identify_until_ - now) > 0) {
    c = blink(WHITE, 300, now);
  } else if (static_cast<int32_t>(flash_until_ - now) > 0) {
    c = flash_color_;
  } else {
    switch (state_) {
      case LinkState::Searching:
        c = breathe(Rgb{60, 60, 60}, 3000, now);
        break;
      case LinkState::Pairing:
        c = blink(Rgb{255, 110, 0}, 600, now);
        break;
      case LinkState::Linked:
        switch (mode_) {
          case Mode::Idle: {
            bool low = batt_pct_ != proto::BATT_UNKNOWN && batt_pct_ < 10;
            c = low ? breathe(Rgb{0, 0, 60}, 2000, now) : Rgb{0, 0, 16};
            break;
          }
          case Mode::Active:
            c = effect_.render(now);
            break;
          case Mode::Standby:
            break;
          case Mode::Calibrate:
            c = Rgb{0, 16, 0};
            break;
        }
        break;
    }
  }
  return scale(c, cfg_.brightness);
}
