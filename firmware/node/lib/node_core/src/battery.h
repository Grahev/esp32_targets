// Battery voltage and charge from the A0 reading. The scale (microvolts per
// ADC count) is calibrated per node from the app with a multimeter reading.
#pragma once

#include <stdint.h>

constexpr uint16_t BATT_SCALE_DEFAULT_UV = 4102;  // 1024 counts = 4.2 V (v1 placeholder)

uint16_t batteryMv(uint16_t raw, uint16_t scale_uv);
// Li-ion discharge curve; proto::BATT_UNKNOWN when no battery seems connected
uint8_t batteryPct(uint16_t mv);
