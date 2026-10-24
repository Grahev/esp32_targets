// Hub settings (/settings.json), edited in the app's Settings screen.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include <string>

#include "ports.h"

struct Settings {
  std::string name = "Airsoft-Master";  // also the WiFi network name
  std::string password;                  // empty = open network (default)
  uint8_t channel = 1;
  uint8_t brightness = 150;  // pushed to every node
  bool auto_accept = true;   // new targets join without a tap
  uint8_t max_nodes = 5;
  uint8_t hb_interval_s = 2;
  bool sounds = true;  // phone beeps (the app reads it)
  std::string difficulty = "Normal";
  uint8_t virtual_nodes = 0;  // developer: simulated targets
  bool virtual_autoshoot = true;
  bool wizard_done = false;
  uint16_t system_id = 0;  // random, set on first boot

  void toJson(JsonObject o, bool with_secrets) const;
  // Applies the fields present in `in`. Returns false with a reason on the
  // first invalid value; nothing is changed then.
  bool update(JsonObjectConst in, std::string& err);
  // Did a change need the WiFi access point to restart?
  static bool wifiChanged(const Settings& a, const Settings& b) {
    return a.name != b.name || a.password != b.password || a.channel != b.channel;
  }

  bool load(Fs& fs);
  bool save(Fs& fs) const;
};
