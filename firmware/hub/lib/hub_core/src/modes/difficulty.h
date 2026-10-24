// Difficulty tables shared by Time Attack+ and Shoot/No-Shoot (from v1).
#pragma once

#include <stdint.h>

#include <string>

namespace difficulty {

constexpr int COUNT = 4;
extern const char* const NAMES[COUNT];
// Minimum lit targets per 30 s stage (0 s, 30 s, ... 150 s+)
extern const uint8_t MIN_TARGETS[COUNT][6];

int index(const std::string& name);  // Normal if unknown
// Pause before the next target after a hit: 1.2 s, 0.8 s, then 0.5 s
uint32_t spawnDelayMs(int stage);

}  // namespace difficulty
