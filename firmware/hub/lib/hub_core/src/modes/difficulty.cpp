#include "difficulty.h"

namespace difficulty {

const char* const NAMES[COUNT] = {"Easy", "Normal", "Hard", "Extreme"};

const uint8_t MIN_TARGETS[COUNT][6] = {
    {1, 1, 1, 1, 1, 2},  // Easy
    {1, 1, 2, 2, 2, 2},  // Normal
    {1, 1, 2, 2, 2, 3},  // Hard
    {2, 2, 2, 3, 3, 3},  // Extreme
};

int index(const std::string& name) {
  for (int i = 0; i < COUNT; i++)
    if (name == NAMES[i]) return i;
  return 1;
}

uint32_t spawnDelayMs(int stage) { return stage == 0 ? 1200 : stage == 1 ? 800 : 500; }

}  // namespace difficulty
