# Hardware

Schematic of the system **as built** (v2, October 2026): one ESP32 hub and up to 5 identical ESP8266 targets. The boards are not wired to each other; they talk over ESP-NOW.

| File | What it is |
|------|------------|
| `kicad/esp32_targets.kicad_pro` | KiCad project. Open it in KiCad 6 or newer (7, 8 and 9 convert it on save) |
| `kicad/esp32_targets.kicad_sch` | Root sheet: overview, links to the two sheets |
| `kicad/node.kicad_sch` | Target node |
| `kicad/hub.kicad_sch` | Hub |
| `schematic_preview.svg` | The same three sheets, viewable in any browser |
| `tools/gen_schematic.py` | Generates all of the above |

The symbols are embedded in the files, so KiCad needs no extra libraries. Footprints are not assigned yet: the schematic is for building by hand.

**Editing.** You can edit the schematic in KiCad, or edit `gen_schematic.py` and run `python3 hardware/tools/gen_schematic.py`, but not both. Once it has been edited in KiCad, running the script again would overwrite those edits. Before writing anything, the script checks that every pin is on exactly one net or marked no-connect, and that the nets match its table.

## Target node (per target)

| Ref | Part | Notes |
|-----|------|-------|
| U1 | WeMos D1 Mini (ESP8266, CH340) | |
| U2 | WeMos D1 Mini Battery Shield v1.3 | Stacked under or over the D1 Mini. Close **J2** to read the battery on A0 |
| BT1 | 1S Li-ion/LiPo 3.7 V, JST-PH 2.0 plug | **Check the plug polarity.** Cells from different sellers are wired both ways |
| M1 | SW-420 vibration module (VCC, GND, DO) | |
| D1 | WS2812B (single LED or breakout) | |
| R1 | 330 Ω in the LED data line | Recommended |
| C1 | 100 µF 10 V across the LED supply | Recommended |
| SW1 | Small on/off switch in the battery line | Optional. With it off, the shield cannot charge the cell |
| JP1 | Choice of LED pin: D3 or D2 | A wire to one or the other. On a PCB this would be a solder jumper |

### Wiring

The D1 Mini headers, top (antenna end) to bottom:

| Left header | Connects to | Right header | Connects to |
|-------------|-------------|--------------|-------------|
| RST | — | TX | — (USB serial) |
| A0 | battery, through the shield's J2 | RX | — (USB serial) |
| D0 | free | **D1 / GPIO5** | SW-420 **DO** |
| D5 | free | **D2 / GPIO4** | LED **DIN** (new targets) |
| D6 | free | **D3 / GPIO0** | LED **DIN** (current targets) |
| D7 | free | D4 / GPIO2 | — (on-board LED, boot pin) |
| D8 | free | GND | SW-420 GND, LED GND |
| **3V3** | SW-420 **VCC** | **5V** | LED **VDD** (from the shield's boost) |

- **LED pin.** Current targets use D3/GPIO0. That is a boot pin: if the LED holds it low at power-up, the board starts in flash mode. Wire new targets to D2/GPIO4, then set **LED pin** for that target in the app (Targets → target → ⋯).
- **LED data level.** A WS2812B on 5 V with 3.3 V data is outside spec (it wants 0.7 × VDD), but it works for one LED. If it flickers, power the LED from 3V3 instead.
- **Sensor.** Power the SW-420 from 3V3 so its output is 3.3 V logic. The pot on the module sets the coarse sensitivity. Fine-tune with lockout and pulses in the app's Sensor test.

### Battery reading and calibration

With J2 closed, the shield feeds BAT+ through 130 kΩ into A0. The D1 Mini has its own 220 k / 100 k divider on A0, so the ADC sees `Vbat × 100 / 450`. Full scale (1.0 V) is therefore 4.5 V, about 4.4 mV per count.

The firmware's default scale (`batt_scale_uv = 4102` in `firmware/node/lib/node_core/src/node_logic.h`) assumes a full scale of 4.2 V. An uncalibrated target therefore reads about 7% low. Calibrate each target once: measure the cell with a multimeter, then enter the reading in the app (Targets → target → Battery calibration). With J2 open, A0 reads near zero and the app shows the battery as unknown.

## Hub

| Part | Notes |
|------|-------|
| ESP32 DevKit (ESP32-D0WD-V3, CP2102, 4 MB flash, no PSRAM) | Pin numbers in the symbol follow the 30-pin DOIT DevKit V1. 38-pin boards have the same GPIOs in a different order |
| USB power bank or charger | About 0.5 W |

Nothing else is wired to the hub. For future add-ons, use GPIO4, 5, 13, 14, 16–19, 21–23, 25–27, 32 or 33. GPIO34–39 are input only. Avoid GPIO0, 2, 12 and 15 (boot straps) and GPIO1 and 3 (USB serial).
