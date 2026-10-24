// Host tests for the node logic: pio test -e native
#include <unity.h>

#include <vector>

#include "battery.h"
#include "effects.h"
#include "hit_filter.h"
#include "node_logic.h"

using proto::Msg;

// ------------------------------------------------------------ fakes

struct Sent {
  bool broadcast;
  std::vector<uint8_t> data;
  proto::Header h() const {
    proto::Header x;
    proto::parseHeader(data.data(), data.size(), x);
    return x;
  }
  Msg type() const { return static_cast<Msg>(h().type); }
};

struct FakeIo : NodeIo {
  std::vector<Sent> sent;
  bool accept_send = true;
  uint8_t channel = 0;
  int saves = 0;
  bool rebooted = false;
  std::vector<uint8_t> ota;
  uint32_t ota_size = 0;
  bool ota_md5_ok = true;
  bool aborted = false;

  bool send(const uint8_t* mac, const uint8_t* data, size_t len) override {
    if (!accept_send) return false;
    sent.push_back(Sent{mac == nullptr, std::vector<uint8_t>(data, data + len)});
    return true;
  }
  void setChannel(uint8_t c) override { channel = c; }
  void saveConfig(const NodeConfig&) override { saves++; }
  void reboot() override { rebooted = true; }
  bool otaBegin(uint32_t size, const uint8_t*) override {
    ota.clear();
    ota_size = size;
    return size < 500000;
  }
  bool otaWrite(const uint8_t* d, size_t n) override {
    ota.insert(ota.end(), d, d + n);
    return true;
  }
  bool otaEnd() override { return ota_md5_ok && ota.size() == ota_size; }
  void otaAbort() override { aborted = true; }
  void log(const char*) override {}

  int count(Msg t) const {
    int n = 0;
    for (auto& s : sent) n += s.type() == t;
    return n;
  }
  const Sent* last(Msg t) const {
    for (auto it = sent.rbegin(); it != sent.rend(); ++it)
      if (it->type() == t) return &*it;
    return nullptr;
  }
};

const uint8_t HUB[6] = {0x3c, 0x8a, 0x1f, 0x7f, 0x70, 0x29};
const uint8_t OTHER[6] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
const uint16_t SID = 0x4242;
const NodeInfo INFO{2, 0, 0, 1, proto::CAP_EFFECTS | proto::CAP_OTA};

struct Rig {
  FakeIo io;
  NodeConfig cfg;
  NodeLogic logic{io, cfg, INFO};
  uint32_t now = 1000;
  uint16_t hub_seq = 0;

  Rig() { logic.begin(now); }

  // Advance time in 10 ms steps; every send completes with `ok`
  void run(uint32_t ms, bool ok = true) {
    for (uint32_t t = 0; t < ms; t += 10) {
      now += 10;
      logic.tick(now);
      logic.onSendDone(ok, now);  // ignored when nothing is on air
    }
  }

  template <typename P>
  void fromHub(Msg type, const P& p, const uint8_t* mac = HUB, uint16_t sid = SID, size_t len = sizeof(P)) {
    uint8_t buf[proto::MAX_FRAME];
    size_t n = proto::encode(buf, proto::makeHeader(type, sid, 1, ++hub_seq), p, len);
    logic.onFrame(mac, buf, n, now);
  }
  void fromHubEmpty(Msg type) {
    uint8_t buf[proto::MAX_FRAME];
    size_t n = proto::encodeEmpty(buf, proto::makeHeader(type, SID, 1, ++hub_seq));
    logic.onFrame(HUB, buf, n, now);
  }
  void welcome(bool accepted, uint8_t slot = 1, uint8_t mode = 0, const uint8_t* mac = HUB, uint16_t sid = SID) {
    proto::Welcome w{slot, static_cast<uint8_t>(accepted), 1, 2, mode};
    fromHub(Msg::Welcome, w, mac, sid);
  }
  void link(uint8_t mode = 0) {
    welcome(true, 1, mode);
    run(20);
  }
  void led(proto::Effect e, uint8_t r, uint8_t g, uint8_t b, uint8_t id, uint16_t p1 = 0, uint16_t p2 = 0) {
    proto::Led l{static_cast<uint8_t>(e), r, g, b, p1, p2, id};
    fromHub(Msg::Led, l);
  }
};

// ------------------------------------------------------------ effects

void test_effect_solid_and_resend() {
  EffectPlayer e;
  proto::Led red{1, 255, 0, 0, 0, 0, 7};
  TEST_ASSERT_TRUE(e.apply(red, 100));
  TEST_ASSERT_EQUAL_UINT32(100, e.litAt());
  TEST_ASSERT_FALSE(e.apply(red, 2100));  // re-send: litAt unchanged
  TEST_ASSERT_EQUAL_UINT32(100, e.litAt());
  TEST_ASSERT_TRUE(e.render(3000) == (Rgb{255, 0, 0}));
}

void test_effect_cleared_id_not_relit() {
  EffectPlayer e;
  proto::Led red{1, 255, 0, 0, 0, 0, 7};
  e.apply(red, 0);
  e.clear(500);
  TEST_ASSERT_FALSE(e.lit(600));
  TEST_ASSERT_FALSE(e.apply(red, 700));  // stale re-send after the hit
  TEST_ASSERT_FALSE(e.lit(700));
  proto::Led next{1, 255, 0, 0, 0, 0, 8};
  TEST_ASSERT_TRUE(e.apply(next, 800));
}

void test_effect_blink_count_and_flash_end() {
  EffectPlayer e;
  proto::Led blink{2, 0, 0, 255, 200, 3, 1};
  e.apply(blink, 0);
  TEST_ASSERT_TRUE(e.render(50) == (Rgb{0, 0, 255}));
  TEST_ASSERT_TRUE(e.render(150).isOff());
  TEST_ASSERT_TRUE(e.lit(550));
  TEST_ASSERT_FALSE(e.lit(600));
  proto::Led flash{4, 255, 255, 255, 100, 0, 2};
  e.apply(flash, 1000);
  TEST_ASSERT_FALSE(e.render(1050).isOff());
  TEST_ASSERT_TRUE(e.render(1100).isOff());
}

void test_effect_ramp() {
  EffectPlayer e;
  proto::Led ramp{5, 0, 255, 0, 1000, 0, 3};
  e.apply(ramp, 0);
  TEST_ASSERT_TRUE(e.lit(0));
  TEST_ASSERT_UINT8_WITHIN(2, 128, e.render(500).g);
  TEST_ASSERT_EQUAL_UINT8(255, e.render(1500).g);
}

// ------------------------------------------------------------ hit filter, battery

void test_filter_debounce() {
  HitFilter f;
  f.configure(300, 1, 30);
  TEST_ASSERT_TRUE(f.onEdge(1000).hit);
  TEST_ASSERT_FALSE(f.onEdge(1100).hit);
  TEST_ASSERT_FALSE(f.onEdge(1299).hit);
  TEST_ASSERT_TRUE(f.onEdge(1301).hit);
}

void test_filter_needs_edges_in_window() {
  HitFilter f;
  f.configure(300, 3, 30);
  TEST_ASSERT_FALSE(f.onEdge(1000).hit);
  TEST_ASSERT_FALSE(f.onEdge(1010).hit);
  HitResult r = f.onEdge(1020);
  TEST_ASSERT_TRUE(r.hit);
  TEST_ASSERT_EQUAL_UINT32(1000, r.at_ms);
  TEST_ASSERT_EQUAL_UINT8(3, r.edges);
  // a lone edge, then the window expires: no hit
  TEST_ASSERT_FALSE(f.onEdge(2000).hit);
  f.poll(2100);
  TEST_ASSERT_FALSE(f.onEdge(2110).hit);
  TEST_ASSERT_FALSE(f.onEdge(2120).hit);
}

void test_battery_curve() {
  TEST_ASSERT_EQUAL_UINT8(100, batteryPct(4200));
  TEST_ASSERT_EQUAL_UINT8(50, batteryPct(3830));
  TEST_ASSERT_EQUAL_UINT8(0, batteryPct(3200));
  TEST_ASSERT_EQUAL_UINT8(proto::BATT_UNKNOWN, batteryPct(100));
  TEST_ASSERT_EQUAL_UINT16(4200, batteryMv(1024, 4102));
}

// ------------------------------------------------------------ link

void test_search_hello_and_channel_hop() {
  Rig r;
  r.run(260);
  TEST_ASSERT_GREATER_OR_EQUAL(2, r.io.count(Msg::Hello));
  TEST_ASSERT_TRUE(r.io.sent[0].broadcast);
  TEST_ASSERT_EQUAL_UINT16(0, r.io.sent[0].h().system_id);
  r.run(600);
  TEST_ASSERT_EQUAL_UINT8(2, r.io.channel);  // 3 hellos per channel, then next
}

void test_welcome_links_and_heartbeats() {
  Rig r;
  r.welcome(true, 3, 0);
  TEST_ASSERT_EQUAL(LinkState::Linked, r.logic.state());
  TEST_ASSERT_EQUAL_UINT8(3, r.cfg.node_id);
  TEST_ASSERT_EQUAL_UINT16(SID, r.cfg.system_id);
  TEST_ASSERT_EQUAL(1, r.io.saves);
  r.run(2500);
  const Sent* hb = r.io.last(Msg::Heartbeat);
  TEST_ASSERT_NOT_NULL(hb);
  TEST_ASSERT_FALSE(hb->broadcast);
  TEST_ASSERT_EQUAL_UINT16(SID, hb->h().system_id);
  TEST_ASSERT_EQUAL_UINT8(3, hb->h().node_id);
}

void test_pending_then_accepted() {
  Rig r;
  r.welcome(false, 0);
  TEST_ASSERT_EQUAL(LinkState::Pairing, r.logic.state());
  r.run(1100);
  const Sent* hello = r.io.last(Msg::Hello);
  TEST_ASSERT_FALSE(hello->broadcast);  // unicast to the hub while pairing
  r.welcome(true, 1);
  TEST_ASSERT_EQUAL(LinkState::Linked, r.logic.state());
}

void test_other_system_ignored_until_search_is_long() {
  Rig r;
  r.link();
  r.fromHubEmpty(Msg::Forget);  // unpair...
  r.cfg.system_id = SID;        // ...but pretend we remember SID (paired, hub gone)
  r.cfg.has_hub = true;
  r.welcome(true, 2, 0, OTHER, 0x9999);
  TEST_ASSERT_EQUAL(LinkState::Searching, r.logic.state());
  r.run(NodeLogic::FORGET_SYSTEM_AFTER_MS + 100);
  const Sent* hello = r.io.last(Msg::Hello);
  TEST_ASSERT_EQUAL_UINT16(0, hello->h().system_id);
  r.welcome(true, 2, 0, OTHER, 0x9999);
  TEST_ASSERT_EQUAL(LinkState::Linked, r.logic.state());
  TEST_ASSERT_EQUAL_UINT16(0x9999, r.cfg.system_id);
}

void test_missed_heartbeats_go_back_to_search() {
  Rig r;
  r.link();
  r.run(2000 * (NodeLogic::MAX_MISSED_HEARTBEATS + 1) + 500);  // hub never answers
  TEST_ASSERT_EQUAL(LinkState::Searching, r.logic.state());
}

void test_radio_failures_go_back_to_search() {
  Rig r;
  r.link();
  r.run(2000 * 3 + 500, false);  // every unicast fails
  TEST_ASSERT_EQUAL(LinkState::Searching, r.logic.state());
}

// ------------------------------------------------------------ game

void test_led_only_in_active_and_hit_reports_rt() {
  Rig r;
  r.link(0);
  r.led(proto::Effect::Solid, 255, 0, 0, 5);
  TEST_ASSERT_TRUE(r.logic.led(r.now) == (Rgb{0, 0, 9}));  // idle: ignored, dim blue (16 * 150/255)
  proto::SetMode m{1};
  r.fromHub(Msg::SetMode, m);
  r.led(proto::Effect::Solid, 255, 0, 0, 5);
  TEST_ASSERT_TRUE(r.logic.led(r.now) == (Rgb{150, 0, 0}));  // brightness 150
  uint32_t lit = r.now;
  r.run(640);
  r.logic.onEdge(lit + 640);
  r.run(20);
  const Sent* hit = r.io.last(Msg::Hit);
  TEST_ASSERT_NOT_NULL(hit);
  proto::Hit p;
  proto::parsePayload(hit->data.data(), hit->data.size(), p);
  TEST_ASSERT_EQUAL_UINT16(640, p.reaction_ms);
  TEST_ASSERT_EQUAL_UINT8(5, p.effect_id);
  r.run(100);  // after the white flash the target is dark, and a re-send doesn't relight it
  TEST_ASSERT_TRUE(r.logic.led(r.now).isOff());
  r.led(proto::Effect::Solid, 255, 0, 0, 5);
  TEST_ASSERT_TRUE(r.logic.led(r.now).isOff());
}

void test_hit_on_dark_target_has_no_rt() {
  Rig r;
  r.link(1);
  r.logic.onEdge(r.now);
  r.run(20);
  proto::Hit p;
  const Sent* hit = r.io.last(Msg::Hit);
  proto::parsePayload(hit->data.data(), hit->data.size(), p);
  TEST_ASSERT_EQUAL_UINT16(proto::RT_NONE, p.reaction_ms);
}

void test_config_applied_saved_acked() {
  Rig r;
  r.link();
  int saves = r.io.saves;
  proto::Config c{};
  c.count = 2;
  c.items[0] = proto::ConfigItem{static_cast<uint8_t>(proto::Key::Brightness), 80};
  c.items[1] = proto::ConfigItem{static_cast<uint8_t>(proto::Key::DebounceMs), 500};
  r.fromHub(Msg::Config, c, HUB, SID, proto::configLen(c));
  TEST_ASSERT_EQUAL_UINT8(80, r.cfg.brightness);
  TEST_ASSERT_EQUAL_UINT16(500, r.cfg.debounce_ms);
  TEST_ASSERT_EQUAL(saves + 1, r.io.saves);
  r.run(20);
  const Sent* ack = r.io.last(Msg::Ack);
  proto::Ack a;
  proto::parsePayload(ack->data.data(), ack->data.size(), a);
  TEST_ASSERT_EQUAL_UINT8(static_cast<uint8_t>(Msg::Config), a.acked_type);
}

// ------------------------------------------------------------ OTA

proto::Ack lastAck(Rig& r) {
  r.run(100);  // drain the send queue
  proto::Ack a{};
  const Sent* s = r.io.last(Msg::Ack);
  if (s) proto::parsePayload(s->data.data(), s->data.size(), a);
  return a;
}

void otaChunk(Rig& r, uint32_t offset, uint8_t len, uint8_t fill) {
  proto::OtaData d{};
  d.offset = offset;
  d.len = len;
  memset(d.data, fill, len);
  r.fromHub(Msg::OtaData, d, HUB, SID, proto::otaDataLen(d));
}

void test_ota_in_order_dup_and_gap() {
  Rig r;
  r.link();
  proto::OtaBegin b{};
  b.size = 400;
  r.fromHub(Msg::OtaBegin, b);
  TEST_ASSERT_TRUE(r.logic.otaActive());
  otaChunk(r, 0, 200, 1);
  TEST_ASSERT_EQUAL_UINT32(200, lastAck(r).value);
  otaChunk(r, 0, 200, 1);  // duplicate: re-ACK, not written twice
  TEST_ASSERT_EQUAL_UINT32(200, lastAck(r).value);
  otaChunk(r, 300, 100, 3);  // gap
  proto::Ack a = lastAck(r);
  TEST_ASSERT_EQUAL_UINT8(static_cast<uint8_t>(proto::AckStatus::BadOffset), a.status);
  otaChunk(r, 200, 200, 2);
  TEST_ASSERT_EQUAL_UINT32(400, lastAck(r).value);
  TEST_ASSERT_EQUAL(400, (int)r.io.ota.size());
  r.fromHubEmpty(Msg::OtaEnd);
  TEST_ASSERT_EQUAL_UINT8(0, lastAck(r).status);
  r.run(600);
  TEST_ASSERT_TRUE(r.io.rebooted);
}

void test_ota_bad_md5_aborts() {
  Rig r;
  r.link();
  r.io.ota_md5_ok = false;
  proto::OtaBegin b{};
  b.size = 200;
  r.fromHub(Msg::OtaBegin, b);
  otaChunk(r, 0, 200, 1);
  r.fromHubEmpty(Msg::OtaEnd);
  TEST_ASSERT_EQUAL_UINT8(static_cast<uint8_t>(proto::AckStatus::Md5Mismatch), lastAck(r).status);
  TEST_ASSERT_TRUE(r.io.aborted);
  r.run(1000);
  TEST_ASSERT_FALSE(r.io.rebooted);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_effect_solid_and_resend);
  RUN_TEST(test_effect_cleared_id_not_relit);
  RUN_TEST(test_effect_blink_count_and_flash_end);
  RUN_TEST(test_effect_ramp);
  RUN_TEST(test_filter_debounce);
  RUN_TEST(test_filter_needs_edges_in_window);
  RUN_TEST(test_battery_curve);
  RUN_TEST(test_search_hello_and_channel_hop);
  RUN_TEST(test_welcome_links_and_heartbeats);
  RUN_TEST(test_pending_then_accepted);
  RUN_TEST(test_other_system_ignored_until_search_is_long);
  RUN_TEST(test_missed_heartbeats_go_back_to_search);
  RUN_TEST(test_radio_failures_go_back_to_search);
  RUN_TEST(test_led_only_in_active_and_hit_reports_rt);
  RUN_TEST(test_hit_on_dark_target_has_no_rt);
  RUN_TEST(test_config_applied_saved_acked);
  RUN_TEST(test_ota_in_order_dup_and_gap);
  RUN_TEST(test_ota_bad_md5_aborts);
  return UNITY_END();
}
