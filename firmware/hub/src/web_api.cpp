// HTTP API, WebSocket and captive portal. Every handler that touches the hub
// takes HubLock; long work (file uploads) runs outside it.
#include "web_api.h"

#include <ArduinoJson.h>
#include <AsyncJson.h>
#include <LittleFS.h>
#include <MD5Builder.h>
#include <Update.h>
#include <WiFi.h>

#include "platform.h"
#include "version.h"
#include "web/app_gz.h"

namespace {

Hub* hub = nullptr;
WebActions* actions = nullptr;

// Node firmware staged for an update (uploaded, not yet pushed)
uint32_t node_fw_size = 0;
uint8_t node_fw_md5[16] = {0};
MD5Builder node_md5;
File node_fw_file;
bool hub_update_ok = false;
String hub_update_error;

void sendJson(AsyncWebServerRequest* req, int code, JsonDocument& doc) {
  String s;
  serializeJson(doc, s);
  req->send(code, "application/json", s);
}

void sendResult(AsyncWebServerRequest* req, const ApiResult& r) {
  JsonDocument d;
  d["ok"] = r.code < 300;
  d["msg"] = r.msg;
  if (!r.confirm.empty()) d["confirm"] = r.confirm;
  sendJson(req, r.code, d);
}

void busy(AsyncWebServerRequest* req) { sendResult(req, ApiResult::err(503, "Hub busy, try again")); }

bool macParam(AsyncWebServerRequest* req, Mac& mac) {
  const AsyncWebParameter* p = req->getParam("mac");
  return p && Mac::parse(p->value().c_str(), mac);
}

// Streams a file, or `fallback` if it doesn't exist
void sendFile(AsyncWebServerRequest* req, const char* path, const char* fallback) {
  if (LittleFS.exists(path)) {
    req->send(LittleFS, path, "application/json");
  } else {
    req->send(200, "application/json", fallback);
  }
}

bool validModeId(const String& m) {
  if (m.isEmpty() || m.length() > 24) return false;
  for (char c : m)
    if (!isalnum(static_cast<unsigned char>(c)) && c != '_') return false;
  return true;
}

// --- backup: one JSON document, streamed from the files without loading them ---
struct BackupStream {
  struct Part {
    String literal;
    String path;          // empty: literal only
    const char* fallback;
    bool jsonl;           // history: newlines become commas inside an array
  };
  std::vector<Part> parts;
  size_t part = 0;
  size_t pos = 0;  // position inside the current literal / file
  bool in_file = false;

  size_t fill(uint8_t* buf, size_t max) {
    size_t n = 0;
    while (n < max && part < parts.size()) {
      Part& p = parts[part];
      if (!in_file) {
        size_t left = p.literal.length() - pos;
        size_t k = std::min(left, max - n);
        memcpy(buf + n, p.literal.c_str() + pos, k);
        n += k;
        pos += k;
        if (pos < p.literal.length()) break;
        pos = 0;
        if (p.path.isEmpty()) {
          part++;
          continue;
        }
        in_file = true;
      }
      File f = LittleFS.open(p.path, "r");
      size_t size = f ? f.size() : 0;
      if (!f || !size) {
        if (f) f.close();
        const char* fb = p.fallback;
        size_t fl = strlen(fb);
        if (max - n < fl) break;  // next call
        memcpy(buf + n, fb, fl);
        n += fl;
      } else {
        f.seek(pos);
        size_t k = f.read(buf + n, std::min(size - pos, max - n));
        f.close();
        if (p.jsonl)
          for (size_t i = 0; i < k; i++)
            if (buf[n + i] == '\n') buf[n + i] = ',';
        n += k;
        pos += k;
        if (pos < size) break;
      }
      in_file = false;
      pos = 0;
      part++;
    }
    return n;
  }
};

void handleBackup(AsyncWebServerRequest* req) {
  auto* s = new BackupStream();
  s->parts.push_back({"{\"format\":\"targets-backup\",\"version\":2,\"fw\":\"" TARGETS_FW_VERSION "\",\"settings\":",
                      "/settings.json", "{}", false});
  s->parts.push_back({",\"nodes\":", "/nodes.json", "[]", false});
  s->parts.push_back({",\"players\":", "/players.json", "[]", false});
  s->parts.push_back({",\"scores\":{", "", "", false});
  bool first = true;
  for (auto& m : gameModes()) {
    String key = String(first ? "" : ",") + "\"" + m.id + "\":";
    first = false;
    s->parts.push_back({key, String("/scores/") + m.id + ".json", "[]", false});
  }
  s->parts.push_back({"},\"history\":[", "/history.jsonl", "", true});
  s->parts.push_back({"null]}", "", "", false});
  std::shared_ptr<BackupStream> stream(s);
  AsyncWebServerResponse* res = req->beginChunkedResponse(
      "application/json", [stream](uint8_t* buf, size_t max, size_t) -> size_t { return stream->fill(buf, max); });
  res->addHeader("Content-Disposition", "attachment; filename=\"targets-backup.json\"");
  req->send(res);
}

// --- restore: the app uploads one part at a time (keeps RAM use small) ---
void handleRestorePart(AsyncWebServerRequest* req, const String& body) {
  const AsyncWebParameter* p = req->getParam("part");
  if (!p) return sendResult(req, ApiResult::err(400, "Missing part"));
  String part = p->value();
  String path;
  if (part == "settings" || part == "nodes" || part == "players") {
    path = "/" + part + ".json";
  } else if (part.startsWith("scores/") && validModeId(part.substring(7))) {
    path = "/" + part + ".json";
  } else if (part == "history") {
    path = "/history.jsonl";
  } else {
    return sendResult(req, ApiResult::err(400, "Unknown part"));
  }
  if (part != "history") {
    JsonDocument d;
    if (deserializeJson(d, body)) return sendResult(req, ApiResult::err(400, "Not valid JSON: " + std::string(part.c_str())));
  }
  LittleFsStore fs;
  if (part.startsWith("scores/")) LittleFS.mkdir("/scores");
  if (!fs.write(path.c_str(), std::string(body.c_str(), body.length()))) {
    return sendResult(req, ApiResult::err(500, "Could not write " + std::string(path.c_str())));
  }
  sendResult(req, ApiResult::ok("Restored " + std::string(part.c_str())));
}

// Collects a request body (up to max bytes) into a String in _tempObject
void collectBody(AsyncWebServerRequest* req, uint8_t* data, size_t len, size_t index, size_t total, size_t max) {
  if (total > max) return;
  if (index == 0) req->_tempObject = new String();
  String* s = static_cast<String*>(req->_tempObject);
  if (s) s->concat(reinterpret_cast<const char*>(data), len);
}

String takeBody(AsyncWebServerRequest* req) {
  String* s = static_cast<String*>(req->_tempObject);
  String out = s ? *s : String();
  delete s;
  req->_tempObject = nullptr;
  return out;
}

// JSON POST helper: body parsed, hub locked
template <typename F>
void jsonPost(AsyncWebServer& server, const char* path, F fn) {
  auto* h = new AsyncCallbackJsonWebHandler(path, [fn](AsyncWebServerRequest* req, JsonVariant& json) {
    HubLock lock;
    if (!lock.ok()) return busy(req);
    fn(req, json.as<JsonObjectConst>());
  });
  h->setMethod(HTTP_POST);
  h->setMaxContentLength(8 * 1024);
  server.addHandler(h);
}

const char* const CAPTIVE_PROBES[] = {"/generate_204", "/gen_204",       "/hotspot-detect.html",
                                      "/library/test/success.html",      "/connecttest.txt",
                                      "/ncsi.txt",     "/redirect",      "/canonical.html",
                                      "/success.txt",  "/fwlink"};

}  // namespace

void setupWeb(AsyncWebServer& server, AsyncWebSocket& ws, Hub& h, WebActions& a) {
  hub = &h;
  actions = &a;

  // --- the app ---
  server.on("/", HTTP_GET, [](AsyncWebServerRequest* req) {
    if (req->hasHeader("If-None-Match") && req->header("If-None-Match") == APP_ETAG) {
      req->send(304);
      return;
    }
    AsyncWebServerResponse* res = req->beginResponse(200, "text/html", APP_GZ, APP_GZ_LEN);
    res->addHeader("Content-Encoding", "gzip");
    res->addHeader("ETag", APP_ETAG);
    res->addHeader("Cache-Control", "no-cache");
    req->send(res);
  });

  // --- captive portal: phones probe these to detect a sign-in page ---
  for (const char* p : CAPTIVE_PROBES) {
    server.on(p, HTTP_ANY, [](AsyncWebServerRequest* req) { req->redirect("http://192.168.4.1/"); });
  }
  server.onNotFound([](AsyncWebServerRequest* req) {
    String host = req->host();
    if (host != "192.168.4.1" && host != "targets.local" && !host.isEmpty()) {
      req->redirect("http://192.168.4.1/");
      return;
    }
    if (req->method() == HTTP_OPTIONS) {
      req->send(204);
      return;
    }
    sendResult(req, ApiResult::err(404, "Not found"));
  });

  // --- read ---
  server.on("/api/v1/state", HTTP_GET, [](AsyncWebServerRequest* req) {
    HubLock lock;
    if (!lock.ok()) return busy(req);
    JsonDocument d;
    hub->stateJson(d.to<JsonObject>());
    sendJson(req, 200, d);
  });
  server.on("/api/v1/modes", HTTP_GET, [](AsyncWebServerRequest* req) {
    std::string s;
    hub->modesJson(s);  // constant data, no lock needed
    req->send(200, "application/json", s.c_str());
  });
  server.on("/api/v1/scores", HTTP_GET, [](AsyncWebServerRequest* req) {
    const AsyncWebParameter* p = req->getParam("mode");
    if (!p || !validModeId(p->value())) return sendResult(req, ApiResult::err(400, "Unknown mode"));
    sendFile(req, Records::scoresPath(p->value().c_str()).c_str(), "[]");
  });
  server.on("/api/v1/history", HTTP_GET,
            [](AsyncWebServerRequest* req) { sendFile(req, Records::historyPath(), ""); });
  server.on("/api/v1/players", HTTP_GET, [](AsyncWebServerRequest* req) {
    HubLock lock;
    if (!lock.ok()) return busy(req);
    JsonDocument d;
    hub->records().playersJson(d.to<JsonArray>());
    sendJson(req, 200, d);
  });
  server.on("/api/v1/diag", HTTP_GET, [](AsyncWebServerRequest* req) {
    JsonDocument d;
    actions->diag(d.to<JsonObject>());
    sendJson(req, 200, d);
  });
  server.on("/api/v1/backup", HTTP_GET, handleBackup);

  // --- write ---
  jsonPost(server, "/api/v1/settings",
           [](AsyncWebServerRequest* req, JsonObjectConst in) { sendResult(req, hub->updateSettings(in)); });
  jsonPost(server, "/api/v1/time", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    hub->setTime(in["epoch_ms"] | 0ULL);
    sendResult(req, ApiResult::ok());
  });
  jsonPost(server, "/api/v1/game/start", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    sendResult(req, hub->startGame(in["mode"] | "", in["settings"], in["player"] | 0, in["force"] | false));
  });
  server.on("/api/v1/game/stop", HTTP_POST, [](AsyncWebServerRequest* req) {
    HubLock lock;
    if (!lock.ok()) return busy(req);
    sendResult(req, hub->stopGame());
  });
  jsonPost(server, "/api/v1/sensor_test",
           [](AsyncWebServerRequest* req, JsonObjectConst in) { sendResult(req, hub->setSensorTest(in["on"] | false)); });
  jsonPost(server, "/api/v1/node", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    Mac mac;
    if (!macParam(req, mac)) return sendResult(req, ApiResult::err(400, "Missing or bad mac"));
    String action = req->hasParam("action") ? req->getParam("action")->value() : "";
    if (action == "accept") return sendResult(req, hub->acceptNode(mac));
    if (action == "forget") return sendResult(req, hub->forgetNode(mac));
    if (action == "identify") return sendResult(req, hub->identifyNode(mac));
    if (action == "reboot") return sendResult(req, hub->rebootNode(mac));
    if (action == "simhit") return sendResult(req, hub->simHit(mac));
    if (action == "update") return sendResult(req, hub->updateNode(mac, in));
    if (action == "calibrate") return sendResult(req, hub->calibrateBattery(mac, in["mv"] | 0));
    sendResult(req, ApiResult::err(400, "Unknown action"));
  });
  jsonPost(server, "/api/v1/players", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    std::string err;
    std::string action = req->hasParam("action") ? req->getParam("action")->value().c_str() : "add";
    int id = req->hasParam("id") ? req->getParam("id")->value().toInt() : 0;
    if (action == "add") {
      int nid = hub->records().addPlayer(in["name"] | "", in["color"] | 0, err);
      if (!nid) return sendResult(req, ApiResult::err(400, err));
      JsonDocument d;
      d["ok"] = true;
      d["id"] = nid;
      return sendJson(req, 200, d);
    }
    if (action == "update") {
      if (!hub->records().updatePlayer(id, in, err)) return sendResult(req, ApiResult::err(400, err));
      return sendResult(req, ApiResult::ok("Saved"));
    }
    if (action == "delete") {
      if (!hub->records().deletePlayer(id)) return sendResult(req, ApiResult::err(404, "No such player"));
      return sendResult(req, ApiResult::ok("Deleted"));
    }
    sendResult(req, ApiResult::err(400, "Unknown action"));
  });

  // Restore one part of a backup (raw body, up to 40 KB)
  server.on(
      "/api/v1/restore", HTTP_POST,
      [](AsyncWebServerRequest* req) {
        String body = takeBody(req);
        if (body.isEmpty()) return sendResult(req, ApiResult::err(413, "Empty or too large (max 40 KB per part)"));
        HubLock lock;
        if (!lock.ok()) return busy(req);
        if (hub->gameRunning()) return sendResult(req, ApiResult::err(409, "Stop the game first"));
        handleRestorePart(req, body);
      },
      nullptr,
      [](AsyncWebServerRequest* req, uint8_t* data, size_t len, size_t index, size_t total) {
        collectBody(req, data, len, index, total, 40 * 1024);
      });

  jsonPost(server, "/api/v1/reboot", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    actions->rebootIn(800);
    sendResult(req, ApiResult::ok("Restarting"));
  });
  jsonPost(server, "/api/v1/factory_reset", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    if (String(in["confirm"] | "") != "RESET") return sendResult(req, ApiResult::err(400, "Type RESET to confirm"));
    actions->factoryReset();
    sendResult(req, ApiResult::ok("Erased. Restarting"));
  });

  // --- hub firmware update (multipart upload of firmware.bin) ---
  server.on(
      "/api/v1/ota/hub", HTTP_POST,
      [](AsyncWebServerRequest* req) {
        if (!hub_update_ok) return sendResult(req, ApiResult::err(400, hub_update_error.c_str()));
        actions->rebootIn(1000);
        sendResult(req, ApiResult::ok("Update installed. Restarting"));
      },
      [](AsyncWebServerRequest* req, const String& filename, size_t index, uint8_t* data, size_t len, bool final) {
        if (index == 0) {
          hub_update_ok = false;
          hub_update_error = "";
          {
            HubLock lock;
            if (hub->gameRunning()) {
              hub_update_error = "Stop the game first";
              return;
            }
          }
          if (!Update.begin(UPDATE_SIZE_UNKNOWN, U_FLASH)) {
            hub_update_error = Update.errorString();
            return;
          }
        }
        if (!hub_update_error.isEmpty() || !Update.isRunning()) return;
        if (Update.write(data, len) != len) {
          hub_update_error = Update.errorString();
          Update.abort();
          return;
        }
        if (final) {
          hub_update_ok = Update.end(true);  // checks the image
          if (!hub_update_ok) hub_update_error = Update.errorString();
        }
      });

  // --- target firmware: upload, then push over ESP-NOW ---
  server.on(
      "/api/v1/ota/node", HTTP_POST,
      [](AsyncWebServerRequest* req) {
        if (!node_fw_size) return sendResult(req, ApiResult::err(400, "Upload failed"));
        JsonDocument d;
        d["ok"] = true;
        d["size"] = node_fw_size;
        sendJson(req, 200, d);
      },
      [](AsyncWebServerRequest* req, const String& filename, size_t index, uint8_t* data, size_t len, bool final) {
        if (index == 0) {
          node_fw_size = 0;
          LittleFS.mkdir("/ota");
          node_fw_file = LittleFS.open(Hub::NODE_OTA_PATH, "w", true);
          node_md5.begin();
        }
        if (!node_fw_file) return;
        node_fw_file.write(data, len);
        node_md5.add(data, len);
        if (final) {
          uint32_t size = node_fw_file.size();
          node_fw_file.close();
          node_md5.calculate();
          node_md5.getBytes(node_fw_md5);
          // ESP8266 images start with 0xE9; refuse anything else
          uint8_t magic = 0;
          File f = LittleFS.open(Hub::NODE_OTA_PATH, "r");
          if (f) {
            f.read(&magic, 1);
            f.close();
          }
          node_fw_size = (magic == 0xE9 && size > 100000) ? size : 0;
          if (!node_fw_size) LittleFS.remove(Hub::NODE_OTA_PATH);
        }
      });
  jsonPost(server, "/api/v1/ota/node/start", [](AsyncWebServerRequest* req, JsonObjectConst in) {
    sendResult(req, hub->startNodeOta(node_fw_size, node_fw_md5, in["macs"]));
  });

  // --- live events ---
  ws.onEvent([](AsyncWebSocket*, AsyncWebSocketClient* client, AwsEventType type, void* arg, uint8_t* data,
                size_t len) {
    if (type == WS_EVT_CONNECT) {
      HubLock lock;
      if (!lock.ok()) return;
      JsonDocument d;
      hub->stateJson(d.to<JsonObject>());
      String s;
      serializeJson(d, s);
      client->text(s);
    } else if (type == WS_EVT_DATA) {
      AwsFrameInfo* info = static_cast<AwsFrameInfo*>(arg);
      if (!info->final || info->index != 0 || info->len != len || info->opcode != WS_TEXT || len > 512) return;
      JsonDocument d;
      if (deserializeJson(d, data, len)) return;
      if (d["t"] == "hello") {
        HubLock lock;
        if (lock.ok()) hub->setTime(d["time"] | 0ULL);
      }
    }
  });
  server.addHandler(&ws);
}
