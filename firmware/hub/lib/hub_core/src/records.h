// Players (/players.json), leaderboards (/scores/<mode>.json, top 50 each) and
// the game history (/history.jsonl, one JSON object per line, trimmed to the
// most recent games). The app streams the score and history files as they are.
#pragma once

#include <ArduinoJson.h>
#include <stdint.h>

#include <string>
#include <vector>

#include "ports.h"

struct Player {
  int id = 0;
  std::string name;
  uint8_t color = 0;
  uint32_t games = 0;
};

class Records {
 public:
  static constexpr size_t TOP_N = 50;
  static constexpr size_t HISTORY_MAX_BYTES = 32 * 1024;
  static constexpr size_t HISTORY_KEEP_BYTES = 16 * 1024;
  static constexpr size_t MAX_PLAYERS = 40;

  explicit Records(Fs& fs) : fs_(fs) {}

  void load();
  const std::vector<Player>& players() const { return players_; }
  const Player* player(int id) const;
  int addPlayer(const std::string& name, uint8_t color, std::string& err);  // 0 on error
  bool updatePlayer(int id, JsonObjectConst in, std::string& err);
  bool deletePlayer(int id);
  void playersJson(JsonArray out) const;

  // Inserts into the mode's leaderboard and the history; returns the rank
  // (1 = best) or 0 if it didn't make the top TOP_N.
  int addScore(const std::string& mode, JsonObjectConst entry);

  static std::string scoresPath(const std::string& mode) { return "/scores/" + mode + ".json"; }
  static const char* historyPath() { return "/history.jsonl"; }
  static const char* playersPath() { return "/players.json"; }

 private:
  bool savePlayers();
  void appendHistory(const std::string& mode, JsonObjectConst entry);
  Fs& fs_;
  std::vector<Player> players_;
};
