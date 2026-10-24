#include "records.h"

namespace {
bool validName(const std::string& n, std::string& err) {
  if (n.empty() || n.size() > 20) {
    err = "Name must be 1-20 characters";
    return false;
  }
  return true;
}
}  // namespace

void Records::load() {
  players_.clear();
  std::string s;
  if (!fs_.read(playersPath(), s)) return;
  JsonDocument doc;
  if (deserializeJson(doc, s)) return;
  for (JsonObjectConst o : doc.as<JsonArrayConst>()) {
    Player p;
    p.id = o["id"] | 0;
    p.name = o["name"] | "";
    p.color = o["color"] | 0;
    p.games = o["games"] | 0;
    if (p.id > 0 && !p.name.empty()) players_.push_back(p);
  }
}

const Player* Records::player(int id) const {
  for (auto& p : players_)
    if (p.id == id) return &p;
  return nullptr;
}

int Records::addPlayer(const std::string& name, uint8_t color, std::string& err) {
  if (!validName(name, err)) return 0;
  for (auto& p : players_) {
    if (p.name == name) return p.id;  // same name = same player
  }
  if (players_.size() >= MAX_PLAYERS) {
    err = "Too many players; delete some first";
    return 0;
  }
  int id = 1;
  for (auto& p : players_)
    if (p.id >= id) id = p.id + 1;
  Player p;
  p.id = id;
  p.name = name;
  p.color = color;
  players_.push_back(p);
  savePlayers();
  return id;
}

bool Records::updatePlayer(int id, JsonObjectConst in, std::string& err) {
  for (auto& p : players_) {
    if (p.id != id) continue;
    if (in["name"].is<const char*>()) {
      std::string n = in["name"].as<const char*>();
      if (!validName(n, err)) return false;
      p.name = n;
    }
    if (!in["color"].isNull()) p.color = in["color"] | p.color;
    return savePlayers();
  }
  err = "No such player";
  return false;
}

bool Records::deletePlayer(int id) {
  for (size_t i = 0; i < players_.size(); i++) {
    if (players_[i].id == id) {
      players_.erase(players_.begin() + i);
      return savePlayers();  // their scores keep the name they were saved with
    }
  }
  return false;
}

void Records::playersJson(JsonArray out) const {
  for (auto& p : players_) {
    JsonObject o = out.add<JsonObject>();
    o["id"] = p.id;
    o["name"] = p.name;
    o["color"] = p.color;
    o["games"] = p.games;
  }
}

bool Records::savePlayers() {
  JsonDocument doc;
  playersJson(doc.to<JsonArray>());
  std::string s;
  serializeJson(doc, s);
  return fs_.write(playersPath(), s);
}

int Records::addScore(const std::string& mode, JsonObjectConst entry) {
  const std::string path = scoresPath(mode);
  JsonDocument doc;
  std::string s;
  if (!fs_.read(path.c_str(), s) || deserializeJson(doc, s) || !doc.is<JsonArray>()) {
    if (!s.empty()) fs_.write((path + ".corrupt").c_str(), s);  // never overwrite the only copy
    doc.to<JsonArray>();
  }
  JsonArray arr = doc.as<JsonArray>();
  long score = entry["s"] | 0L;
  size_t pos = 0;
  for (JsonVariant v : arr) {
    if (score > (v["s"] | 0L)) break;
    pos++;
  }
  int rank = 0;
  if (pos < TOP_N) {
    JsonDocument out;
    JsonArray o = out.to<JsonArray>();
    size_t i = 0;
    for (JsonVariant v : arr) {
      if (i == pos) o.add(entry);
      if (o.size() >= TOP_N) break;
      o.add(v);
      i++;
    }
    if (pos >= i && o.size() < TOP_N) o.add(entry);
    std::string w;
    serializeJson(out, w);
    fs_.write(path.c_str(), w);
    rank = static_cast<int>(pos) + 1;
  }
  int pid = entry["p"] | 0;
  for (auto& p : players_) {
    if (p.id == pid) {
      p.games++;
      savePlayers();
    }
  }
  appendHistory(mode, entry);
  return rank;
}

void Records::appendHistory(const std::string& mode, JsonObjectConst entry) {
  JsonDocument doc;
  doc.set(entry);
  doc["m"] = mode;
  std::string line;
  serializeJson(doc, line);
  line += '\n';
  fs_.append(historyPath(), line);
  if (fs_.size(historyPath()) <= HISTORY_MAX_BYTES) return;
  // Keep the newest ~16 KB, cut at a line boundary
  std::string all;
  if (!fs_.read(historyPath(), all)) return;
  size_t cut = all.size() > HISTORY_KEEP_BYTES ? all.size() - HISTORY_KEEP_BYTES : 0;
  cut = all.find('\n', cut);
  if (cut == std::string::npos) return;
  fs_.write(historyPath(), all.substr(cut + 1));
}
