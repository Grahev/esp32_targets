#include "settings.h"

#include "protocol.h"

namespace {
const char* PATH = "/settings.json";
const char* DIFFICULTIES[] = {"Easy", "Normal", "Hard", "Extreme"};

bool validDifficulty(const std::string& d) {
  for (const char* x : DIFFICULTIES)
    if (d == x) return true;
  return false;
}
}  // namespace

void Settings::toJson(JsonObject o, bool with_secrets) const {
  o["name"] = name;
  if (with_secrets) {
    o["password"] = password;
  } else {
    o["has_password"] = !password.empty();
  }
  o["channel"] = channel;
  o["brightness"] = brightness;
  o["auto_accept"] = auto_accept;
  o["max_nodes"] = max_nodes;
  o["hb_interval_s"] = hb_interval_s;
  o["sounds"] = sounds;
  o["difficulty"] = difficulty;
  o["virtual_nodes"] = virtual_nodes;
  o["virtual_autoshoot"] = virtual_autoshoot;
  o["wizard_done"] = wizard_done;
  if (with_secrets) o["system_id"] = system_id;
}

bool Settings::update(JsonObjectConst in, std::string& err) {
  Settings n = *this;
  if (in["name"].is<const char*>()) {
    n.name = in["name"].as<const char*>();
    if (n.name.empty() || n.name.size() > 31) {
      err = "Name must be 1-31 characters";
      return false;
    }
  }
  if (in["password"].is<const char*>()) {
    n.password = in["password"].as<const char*>();
    if (!n.password.empty() && (n.password.size() < 8 || n.password.size() > 63)) {
      err = "Password must be 8-63 characters, or empty for an open network";
      return false;
    }
  }
  if (!in["channel"].isNull()) {
    int c = in["channel"] | 0;
    if (c < 1 || c > 13) {
      err = "Channel must be 1-13";
      return false;
    }
    n.channel = c;
  }
  if (!in["brightness"].isNull()) {
    int b = in["brightness"] | -1;
    if (b < 10 || b > 255) {
      err = "Brightness must be 10-255";
      return false;
    }
    n.brightness = b;
  }
  if (!in["max_nodes"].isNull()) {
    int m = in["max_nodes"] | 0;
    if (m < 1 || m > proto::MAX_NODES_HARD) {
      err = "Max targets must be 1-8";
      return false;
    }
    n.max_nodes = m;
  }
  if (!in["hb_interval_s"].isNull()) {
    int h = in["hb_interval_s"] | 0;
    if (h < 1 || h > 10) {
      err = "Heartbeat must be 1-10 s";
      return false;
    }
    n.hb_interval_s = h;
  }
  if (in["difficulty"].is<const char*>()) {
    n.difficulty = in["difficulty"].as<const char*>();
    if (!validDifficulty(n.difficulty)) {
      err = "Unknown difficulty";
      return false;
    }
  }
  if (!in["virtual_nodes"].isNull()) {
    int v = in["virtual_nodes"] | -1;
    if (v < 0 || v > proto::MAX_NODES_HARD) {
      err = "Virtual targets must be 0-8";
      return false;
    }
    n.virtual_nodes = v;
  }
  if (in["auto_accept"].is<bool>()) n.auto_accept = in["auto_accept"];
  if (in["sounds"].is<bool>()) n.sounds = in["sounds"];
  if (in["virtual_autoshoot"].is<bool>()) n.virtual_autoshoot = in["virtual_autoshoot"];
  if (in["wizard_done"].is<bool>()) n.wizard_done = in["wizard_done"];
  *this = n;
  return true;
}

bool Settings::load(Fs& fs) {
  std::string s;
  if (!fs.read(PATH, s)) return false;
  JsonDocument doc;
  if (deserializeJson(doc, s)) return false;
  std::string err;
  update(doc.as<JsonObjectConst>(), err);  // invalid fields keep their defaults
  system_id = doc["system_id"] | 0;
  return true;
}

bool Settings::save(Fs& fs) const {
  JsonDocument doc;
  toJson(doc.to<JsonObject>(), true);
  std::string s;
  serializeJson(doc, s);
  return fs.write(PATH, s);
}
