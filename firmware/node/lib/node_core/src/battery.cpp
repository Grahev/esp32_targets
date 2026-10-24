#include "battery.h"

#include "protocol.h"

uint16_t batteryMv(uint16_t raw, uint16_t scale_uv) {
  return static_cast<uint16_t>((static_cast<uint32_t>(raw) * scale_uv + 500) / 1000);
}

namespace {
struct Point {
  uint16_t mv;
  uint8_t pct;
};
// Typical single-cell Li-ion under light load
const Point CURVE[] = {{4200, 100}, {4100, 90}, {4000, 80}, {3920, 70}, {3870, 60}, {3830, 50},
                       {3790, 40},  {3750, 30}, {3710, 20}, {3670, 10}, {3550, 5},  {3300, 0}};
}  // namespace

uint8_t batteryPct(uint16_t mv) {
  if (mv < 2500 || mv > 4600) return proto::BATT_UNKNOWN;  // USB only, or not calibrated
  if (mv >= CURVE[0].mv) return 100;
  const int n = sizeof(CURVE) / sizeof(CURVE[0]);
  for (int i = 1; i < n; i++) {
    if (mv >= CURVE[i].mv) {
      const Point& hi = CURVE[i - 1];
      const Point& lo = CURVE[i];
      return static_cast<uint8_t>(lo.pct + (mv - lo.mv) * (hi.pct - lo.pct) / (hi.mv - lo.mv));
    }
  }
  return 0;
}
