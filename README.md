# ESP32 Targets

Reaction targets for airsoft. One **hub** (ESP32) runs the games and a phone app over its own WiFi; up to 5 **targets** (ESP8266 / ESP32-C3) with a hit sensor and an LED talk to it over ESP-NOW. No internet, no app store, no PC needed to play.

- **Games:** Time Attack+, The Breach (memory), Shoot / No-Shoot, Free Practice
- **Phone app:** join the WiFi `Airsoft-Master` and the app opens by itself (or go to http://192.168.4.1)
- **Setup:** switch targets on and they join automatically; a first-run wizard walks you through it
- **Updates** for the hub and the targets from the phone; backup and restore of all scores

Docs: [user guide](docs/v2/USER_GUIDE.md) · [plan and design](docs/v2/V2_PLAN.md) · [radio protocol](docs/v2/PROTOCOL.md) · developer notes in [CLAUDE.md](CLAUDE.md).

## Build

Needs PlatformIO and Node.js 20.

```bash
tools/deploy.sh test   # host tests: node logic, hub logic, full simulated games
tools/deploy.sh all    # tests, flash the node, then the hub (with the web app built in)
```

v1 (MicroPython) is tagged `v1.0` and kept in `legacy/v1/`.
