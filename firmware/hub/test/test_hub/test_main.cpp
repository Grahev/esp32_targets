// Host tests for the hub core: pio test -e native -f test_hub
#include <unity.h>

#include "../fakes.h"

static JsonDocument obj(const char* json) {
  JsonDocument d;
  deserializeJson(d, json);
  return d;
}

// ------------------------------------------------------------ protocol, settings, records

void test_protocol_roundtrip() {
  uint8_t buf[proto::MAX_FRAME];
  proto::Hit hit{640, 9, 2, 17, 123456};
  size_t n = proto::encode(buf, proto::makeHeader(proto::Msg::Hit, 0x1234, 3, 77), hit);
  TEST_ASSERT_EQUAL(18, n);
  proto::Header h;
  TEST_ASSERT_TRUE(proto::parseHeader(buf, n, h));
  TEST_ASSERT_EQUAL_UINT16(0x1234, h.system_id);
  TEST_ASSERT_EQUAL_UINT8(3, h.node_id);
  proto::Hit back;
  TEST_ASSERT_TRUE(proto::parsePayload(buf, n, back));
  TEST_ASSERT_EQUAL_UINT16(640, back.reaction_ms);
  TEST_ASSERT_FALSE(proto::parsePayload(buf, n - 1, back));  // short frame
  buf[0] = 0;
  TEST_ASSERT_FALSE(proto::parseHeader(buf, n, h));  // bad magic
}

void test_settings_validation() {
  Settings s;
  std::string err;
  TEST_ASSERT_FALSE(s.update(obj("{\"password\":\"short\"}").as<JsonObjectConst>(), err));
  TEST_ASSERT_EQUAL_STRING("Airsoft-Master", s.name.c_str());
  TEST_ASSERT_TRUE(s.update(obj("{\"password\":\"\"}").as<JsonObjectConst>(), err));  // open network
  TEST_ASSERT_FALSE(s.update(obj("{\"channel\":14}").as<JsonObjectConst>(), err));
  TEST_ASSERT_TRUE(s.update(obj("{\"password\":\"airsoft123\",\"channel\":6}").as<JsonObjectConst>(), err));
  TEST_ASSERT_EQUAL_STRING("airsoft123", s.password.c_str());
  TEST_ASSERT_EQUAL_UINT8(6, s.channel);
}

void test_scores_ranked_and_capped() {
  MemFs fs;
  Records r(fs);
  for (int i = 0; i < 60; i++) {
    JsonDocument e;
    e["s"] = i;
    r.addScore("time_attack", e.as<JsonObjectConst>());
  }
  JsonDocument top;
  deserializeJson(top, fs.files["/scores/time_attack.json"]);
  TEST_ASSERT_EQUAL(Records::TOP_N, top.size());
  TEST_ASSERT_EQUAL(59, top[0]["s"].as<int>());
  TEST_ASSERT_EQUAL(10, top[49]["s"].as<int>());
  JsonDocument e;
  e["s"] = 30;
  TEST_ASSERT_EQUAL(31, r.addScore("time_attack", e.as<JsonObjectConst>()));  // a tie ranks after the older score
  e["s"] = 1;
  TEST_ASSERT_EQUAL(0, r.addScore("time_attack", e.as<JsonObjectConst>()));  // not in the top 50
}

void test_corrupt_scores_kept_aside() {
  MemFs fs;
  fs.files["/scores/breach.json"] = "[{\"s\":10},";
  Records r(fs);
  JsonDocument e;
  e["s"] = 5;
  TEST_ASSERT_EQUAL(1, r.addScore("breach", e.as<JsonObjectConst>()));
  TEST_ASSERT_TRUE(fs.exists("/scores/breach.json.corrupt"));
}

void test_history_trimmed() {
  MemFs fs;
  Records r(fs);
  for (int i = 0; i < 400; i++) {
    JsonDocument e;
    e["s"] = i;
    e["pad"] = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
    r.addScore("time_attack", e.as<JsonObjectConst>());
  }
  TEST_ASSERT_LESS_OR_EQUAL(Records::HISTORY_MAX_BYTES, fs.size("/history.jsonl"));
  const std::string& h = fs.files["/history.jsonl"];
  TEST_ASSERT_TRUE(h.find("\"s\":399") != std::string::npos);
  TEST_ASSERT_EQUAL('{', h[0]);  // cut at a line boundary
}

void test_players() {
  MemFs fs;
  Records r(fs);
  std::string err;
  int a = r.addPlayer("Kris", 2, err);
  TEST_ASSERT_EQUAL(1, a);
  TEST_ASSERT_EQUAL(a, r.addPlayer("Kris", 3, err));  // same name, same player
  TEST_ASSERT_EQUAL(0, r.addPlayer("", 0, err));
  Records again(fs);
  again.load();
  TEST_ASSERT_EQUAL(1, again.players().size());
}

// ------------------------------------------------------------ pairing and liveness

void test_auto_accept_pairs_node() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  TEST_ASSERT_EQUAL(1, w.online());
  TEST_ASSERT_EQUAL(LinkState::Linked, n.logic->state());
  TEST_ASSERT_EQUAL_UINT8(1, n.cfg.node_id);
  TEST_ASSERT_EQUAL_UINT16(w.hub.settings().system_id, n.cfg.system_id);
  TEST_ASSERT_TRUE(w.fs.files["/nodes.json"].find(n.mac.str()) != std::string::npos);
  TEST_ASSERT_EQUAL(1, w.radio.peers.size());
}

void test_manual_accept() {
  World w;
  w.hub.updateSettings(obj("{\"auto_accept\":false}").as<JsonObjectConst>());
  LinkedNode& n = w.addNode();
  w.run(1000);
  TEST_ASSERT_EQUAL(0, w.online());
  TEST_ASSERT_EQUAL(LinkState::Pairing, n.logic->state());
  TEST_ASSERT_TRUE(w.events.last("nodes").find("pending\":[{") != std::string::npos);
  TEST_ASSERT_EQUAL(200, w.hub.acceptNode(n.mac).code);
  w.run(1500);
  TEST_ASSERT_EQUAL(1, w.online());
  TEST_ASSERT_EQUAL(LinkState::Linked, n.logic->state());
}

void test_slot_limit() {
  World w;
  w.hub.updateSettings(obj("{\"max_nodes\":2}").as<JsonObjectConst>());
  w.addNode();
  w.addNode();
  w.addNode();
  w.run(1500);
  TEST_ASSERT_EQUAL(2, w.online());
  TEST_ASSERT_EQUAL(LinkState::Pairing, w.radio.nodes[2]->logic->state());
}

void test_node_survives_hub_reboot() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  // New hub instance, same files: the node keeps slot 1 without pairing again
  MemFs saved = w.fs;
  World w2(false);
  w2.fs = saved;
  w2.hub.begin(w2.now, 7);
  w2.radio.nodes.push_back(std::move(w.radio.nodes[0]));
  w2.radio.nodes[0]->radio = &w2.radio;
  w2.radio.nodes[0]->powerCycle(w2.now);
  w2.run(1000);
  TEST_ASSERT_EQUAL(1, w2.online());
  TEST_ASSERT_EQUAL_UINT8(1, w2.radio.nodes[0]->cfg.node_id);
  (void)n;
}

void test_offline_after_silence_and_back() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  n.powered = false;
  w.run(9000);
  TEST_ASSERT_EQUAL(0, w.online());
  TEST_ASSERT_EQUAL(0, w.radio.peers.size());
  n.powered = true;
  n.powerCycle(w.now);
  w.run(1000);
  TEST_ASSERT_EQUAL(1, w.online());
}

void test_forget_unpairs_node() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  w.hub.updateSettings(obj("{\"auto_accept\":false}").as<JsonObjectConst>());
  TEST_ASSERT_EQUAL(200, w.hub.forgetNode(n.mac).code);
  w.run(1000);
  TEST_ASSERT_EQUAL(0, w.online());
  TEST_ASSERT_EQUAL_UINT16(0, n.cfg.system_id);
  TEST_ASSERT_EQUAL(LinkState::Pairing, n.logic->state());  // shows up as new again
}

void test_config_pushed_and_identify() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  TEST_ASSERT_EQUAL(200, w.hub.updateNode(n.mac, obj("{\"cfg\":{\"debounce_ms\":450}}").as<JsonObjectConst>()).code);
  w.hub.updateSettings(obj("{\"brightness\":90}").as<JsonObjectConst>());
  w.run(300);
  TEST_ASSERT_EQUAL_UINT16(450, n.cfg.debounce_ms);
  TEST_ASSERT_EQUAL_UINT8(90, n.cfg.brightness);
  TEST_ASSERT_EQUAL(400, w.hub.updateNode(n.mac, obj("{\"cfg\":{\"debounce_ms\":5}}").as<JsonObjectConst>()).code);
  TEST_ASSERT_EQUAL(200, w.hub.identifyNode(n.mac).code);
}

void test_renumber_swaps_slots() {
  World w;
  LinkedNode& a = w.addNode();
  w.run(300);
  LinkedNode& b = w.addNode();
  w.run(500);
  TEST_ASSERT_EQUAL_UINT8(1, a.cfg.node_id);
  TEST_ASSERT_EQUAL_UINT8(2, b.cfg.node_id);
  TEST_ASSERT_EQUAL(200, w.hub.updateNode(b.mac, obj("{\"slot\":1}").as<JsonObjectConst>()).code);
  w.run(300);
  TEST_ASSERT_EQUAL_UINT8(2, a.cfg.node_id);
  TEST_ASSERT_EQUAL_UINT8(1, b.cfg.node_id);
}

void test_battery_calibration() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(3000);
  // node reports 3900 mV; the multimeter says 3.80 V
  TEST_ASSERT_EQUAL(200, w.hub.calibrateBattery(n.mac, 3800).code);
  w.run(300);
  TEST_ASSERT_EQUAL_UINT16(4102 * 3800 / 3900, n.cfg.batt_scale_uv);
}

// ------------------------------------------------------------ games

void test_start_validation() {
  World w;
  JsonDocument cfg;
  TEST_ASSERT_EQUAL(409, w.hub.startGame("time_attack", cfg.as<JsonObjectConst>(), 0, false).code);  // no targets
  w.addNode();
  w.run(500);
  TEST_ASSERT_EQUAL(400, w.hub.startGame("nope", cfg.as<JsonObjectConst>(), 0, false).code);
  TEST_ASSERT_EQUAL(409, w.hub.startGame("shoot_no_shoot", cfg.as<JsonObjectConst>(), 0, false).code);  // needs 2
  TEST_ASSERT_EQUAL(400,
                    w.hub.startGame("time_attack", obj("{\"duration\":99}").as<JsonObjectConst>(), 0, false).code);
  TEST_ASSERT_EQUAL(200, w.hub.startGame("time_attack", cfg.as<JsonObjectConst>(), 0, false).code);
  TEST_ASSERT_EQUAL(200, w.hub.stopGame().code);
  TEST_ASSERT_EQUAL(409, w.hub.stopGame().code);
}

void test_low_battery_needs_confirmation() {
  World w;
  LinkedNode& n = w.addNode();
  n.logic->setBattery(3500, 5, 0);
  w.run(3000);
  JsonDocument cfg;
  ApiResult r = w.hub.startGame("time_attack", cfg.as<JsonObjectConst>(), 0, false);
  TEST_ASSERT_EQUAL(409, r.code);
  TEST_ASSERT_EQUAL_STRING("low_battery", r.confirm.c_str());
  TEST_ASSERT_EQUAL(200, w.hub.startGame("time_attack", cfg.as<JsonObjectConst>(), 0, true).code);
}

void test_time_attack_with_virtual_targets() {
  World w;
  std::string err;
  int pid = w.hub.records().addPlayer("Kris", 1, err);
  w.hub.updateSettings(obj("{\"virtual_nodes\":5}").as<JsonObjectConst>());
  w.run(1500);
  TEST_ASSERT_EQUAL(5, w.online());
  TEST_ASSERT_EQUAL(200, w.hub.startGame("time_attack", obj("{\"duration\":1,\"difficulty\":\"Hard\"}").as<JsonObjectConst>(),
                                         pid, false).code);
  w.run(65000);
  TEST_ASSERT_FALSE(w.hub.gameRunning());
  JsonDocument res = parse(w.events.last("result"));
  TEST_ASSERT_TRUE(res["result"]["saved"].as<bool>());
  TEST_ASSERT_EQUAL(1, res["result"]["rank"].as<int>());
  int hits = res["result"]["stats"]["hits"];
  TEST_ASSERT_GREATER_THAN(30, hits);  // the auto-shooter keeps up
  TEST_ASSERT_EQUAL(5, res["result"]["stats"]["slots"].size());  // every target was used
  TEST_ASSERT_TRUE(w.fs.files["/scores/time_attack.json"].find("\"n\":\"Kris\"") != std::string::npos);
  JsonDocument st;
  w.hub.stateJson(st.to<JsonObject>());
  TEST_ASSERT_EQUAL_STRING("standby", st["mode"]);
  w.run(11000);
  st.clear();
  w.hub.stateJson(st.to<JsonObject>());
  TEST_ASSERT_EQUAL_STRING("idle", st["mode"]);
}

void test_breach_with_virtual_targets() {
  World w;
  w.hub.updateSettings(obj("{\"virtual_nodes\":4}").as<JsonObjectConst>());
  w.run(1500);
  JsonDocument cfg;
  TEST_ASSERT_EQUAL(200, w.hub.startGame("breach", cfg.as<JsonObjectConst>(), 0, false).code);
  w.run(240000);
  TEST_ASSERT_FALSE(w.hub.gameRunning());
  JsonDocument res = parse(w.events.last("result"));
  TEST_ASSERT_EQUAL(10, res["result"]["stats"]["cleared"].as<int>());  // the simulated player never forgets
  TEST_ASSERT_GREATER_THAN(1200, res["result"]["score"].as<int>());
}

void test_shoot_no_shoot_spares_hostages() {
  World w;
  w.hub.updateSettings(obj("{\"virtual_nodes\":3}").as<JsonObjectConst>());
  w.run(1500);
  TEST_ASSERT_EQUAL(200, w.hub.startGame("shoot_no_shoot", obj("{\"duration\":1}").as<JsonObjectConst>(), 0, false).code);
  w.run(65000);
  JsonDocument res = parse(w.events.last("result"));
  TEST_ASSERT_EQUAL(0, res["result"]["stats"]["hostages_hit"].as<int>());
  TEST_ASSERT_GREATER_THAN(10, res["result"]["stats"]["hits"].as<int>());
  TEST_ASSERT_GREATER_THAN(0, res["result"]["stats"]["held"].as<int>());
}

void test_free_practice_not_saved() {
  World w;
  w.hub.updateSettings(obj("{\"virtual_nodes\":2}").as<JsonObjectConst>());
  w.run(1500);
  TEST_ASSERT_EQUAL(200, w.hub.startGame("free_practice", obj("{\"duration\":1}").as<JsonObjectConst>(), 0, false).code);
  w.run(65000);
  JsonDocument res = parse(w.events.last("result"));
  TEST_ASSERT_FALSE(res["result"]["saved"].as<bool>());
  TEST_ASSERT_GREATER_THAN(10, res["result"]["stats"]["hits"].as<int>());
  TEST_ASSERT_FALSE(w.fs.exists("/scores/free_practice.json"));
}

void test_target_lost_mid_game_game_goes_on() {
  World w;
  w.hub.updateSettings(obj("{\"virtual_nodes\":3}").as<JsonObjectConst>());
  w.run(1500);
  w.hub.startGame("time_attack", obj("{\"duration\":2}").as<JsonObjectConst>(), 0, false);
  w.run(30000);
  w.hub.updateSettings(obj("{\"virtual_nodes\":2}").as<JsonObjectConst>());  // target 3 disappears
  w.run(95000);
  JsonDocument res = parse(w.events.last("result"));
  TEST_ASSERT_GREATER_THAN(60, res["result"]["stats"]["hits"].as<int>());
}

void test_real_node_game_and_reaction_time() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  w.hub.startGame("free_practice", obj("{\"pace\":\"Fast\"}").as<JsonObjectConst>(), 0, false);
  auto red = [&] {
    Rgb c = n.logic->led(w.now);
    return c.r > 0 && c.g == 0 && c.b == 0;
  };
  for (int i = 0; i < 800 && !red(); i++) w.run(10);  // countdown, then the target lights red
  Rgb c = n.logic->led(w.now);
  TEST_ASSERT_TRUE(c.r > 0 && c.g == 0);
  w.run(600);
  n.logic->onEdge(w.now);
  w.run(100);
  JsonDocument feed = parse(w.events.last("feed"));
  int rt = feed["rt"];
  TEST_ASSERT_INT_WITHIN(30, 600, rt);  // measured on the node, not including radio delays
}

void test_mode_resync_from_heartbeat() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  w.hub.setSensorTest(true);
  w.run(300);
  TEST_ASSERT_EQUAL(proto::Mode::Calibrate, n.logic->mode());
  n.logic->onEdge(w.now);
  w.run(100);
  TEST_ASSERT_TRUE(w.events.last("sensor").find("\"slot\":1") != std::string::npos);
}

// ------------------------------------------------------------ OTA

void test_node_ota_push() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  std::string image(1234, 'x');
  for (size_t i = 0; i < image.size(); i++) image[i] = static_cast<char>(i * 7);
  w.fs.files[Hub::NODE_OTA_PATH] = image;
  uint8_t md5[16] = {0};
  JsonDocument macs;
  macs.add(n.mac.str());
  TEST_ASSERT_EQUAL(200, w.hub.startNodeOta(image.size(), md5, macs.as<JsonArrayConst>()).code);
  w.run(3000);
  TEST_ASSERT_EQUAL(image.size(), n.ota.size());
  TEST_ASSERT_EQUAL_MEMORY(image.data(), n.ota.data(), image.size());
  w.run(1000);
  TEST_ASSERT_EQUAL(1, n.reboots);
  n.powerCycle(w.now);  // what the reboot does on real hardware
  w.run(1000);
  TEST_ASSERT_FALSE(w.hub.otaRunning());
  TEST_ASSERT_TRUE(w.events.last("ota").find("\"done\":[\"" + n.mac.str()) != std::string::npos);
}

void test_ota_survives_packet_loss() {
  World w;
  LinkedNode& n = w.addNode();
  w.run(500);
  w.radio.loss_pct = 10;
  std::string image(5000, 'a');
  w.fs.files[Hub::NODE_OTA_PATH] = image;
  uint8_t md5[16] = {0};
  JsonDocument macs;
  macs.add(n.mac.str());
  w.hub.startNodeOta(image.size(), md5, macs.as<JsonArrayConst>());
  w.run(30000);
  TEST_ASSERT_EQUAL(image.size(), n.ota.size());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_protocol_roundtrip);
  RUN_TEST(test_settings_validation);
  RUN_TEST(test_scores_ranked_and_capped);
  RUN_TEST(test_corrupt_scores_kept_aside);
  RUN_TEST(test_history_trimmed);
  RUN_TEST(test_players);
  RUN_TEST(test_auto_accept_pairs_node);
  RUN_TEST(test_manual_accept);
  RUN_TEST(test_slot_limit);
  RUN_TEST(test_node_survives_hub_reboot);
  RUN_TEST(test_offline_after_silence_and_back);
  RUN_TEST(test_forget_unpairs_node);
  RUN_TEST(test_config_pushed_and_identify);
  RUN_TEST(test_renumber_swaps_slots);
  RUN_TEST(test_battery_calibration);
  RUN_TEST(test_start_validation);
  RUN_TEST(test_low_battery_needs_confirmation);
  RUN_TEST(test_time_attack_with_virtual_targets);
  RUN_TEST(test_breach_with_virtual_targets);
  RUN_TEST(test_shoot_no_shoot_spares_hostages);
  RUN_TEST(test_free_practice_not_saved);
  RUN_TEST(test_target_lost_mid_game_game_goes_on);
  RUN_TEST(test_real_node_game_and_reaction_time);
  RUN_TEST(test_mode_resync_from_heartbeat);
  RUN_TEST(test_node_ota_push);
  RUN_TEST(test_ota_survives_packet_loss);
  return UNITY_END();
}
