#include "spawner.h"

#include <algorithm>

uint8_t Spawner::pick(GameHost& h, const std::vector<uint8_t>& busy) {
  std::vector<uint8_t> free_slots, candidates;
  for (uint8_t s : h.slots()) {
    if (s > proto::MAX_NODES_HARD) continue;
    if (std::find(busy.begin(), busy.end(), s) == busy.end()) free_slots.push_back(s);
  }
  for (uint8_t s : free_slots)
    if (s != last_hit_) candidates.push_back(s);
  // Only one target in play: it has to come back
  if (candidates.empty() && busy.empty()) candidates = free_slots;
  if (candidates.empty()) return 0;

  // A target that joined mid-game starts level with the least-used one
  uint32_t floor = UINT32_MAX, top = 0;
  for (int s = 1; s <= proto::MAX_NODES_HARD; s++) {
    if (known_[s]) floor = std::min(floor, count_[s]);
  }
  if (floor == UINT32_MAX) floor = 0;
  for (uint8_t s : candidates) {
    if (!known_[s]) {
      known_[s] = true;
      count_[s] = floor;
    }
    top = std::max(top, count_[s]);
  }
  uint32_t total = 0;
  for (uint8_t s : candidates) total += top - count_[s] + 1;
  uint32_t r = h.random(total);
  for (uint8_t s : candidates) {
    uint32_t w = top - count_[s] + 1;
    if (r < w) {
      count_[s]++;
      return s;
    }
    r -= w;
  }
  return candidates.back();
}
