# Airsoft Gemini: Smart Target System

Airsoft Gemini is a wireless, interactive target system designed for airsoft training and gamification. It utilizes **ESP32** and **ESP8266** microcontrollers communicating via **ESP-NOW** for low-latency feedback, with a central **Web Dashboard** for game control and scoring.

## Features

*   **Wireless Connectivity:** Nodes communicate with the Hub wirelessly using ESP-NOW protocols.
*   **Real-time Web Dashboard:** Control games, view live scores, and monitor battery levels from any smartphone or laptop connected to the Hub's WiFi.
*   **Multiple Game Modes:**
    *   **Time Attack+**: Test your speed and precision. Score points by hitting targets; faster reaction times yield bonus points. Includes combo multipliers.
    *   **The Breach**: A sequence memory game. Memorize the pattern of flashing targets and shoot them in the correct order.
*   **Hardware Feedback:** High-brightness NeoPixel LEDs on targets provide instant visual confirmation of hits and game state.
*   **Battery Monitoring:** Remote monitoring of each target's battery voltage and charging status directly from the dashboard.
*   **Idle Behavior:** Nodes enter a power-saving idle state with a dim breathing LED indicator when no game is active.

## Hardware Requirements

### Hub
*   **Microcontroller:** ESP32 Development Board
*   **Power:** USB or 5V Battery

### Nodes (Targets)
*   **Microcontroller:** ESP8266 (Wemos D1 Mini recommended)
*   **Sensor:** Piezo Vibration Sensor or SW-420 (Connected to **D1 / GPIO 5**)
*   **Feedback:** WS2812B NeoPixel LED (Connected to **D3 / GPIO 0**)
*   **Power:** 3.7V LiPo Battery with generic voltage divider on **A0** for monitoring.

## Installation

### 1. Firmware
Flash standard MicroPython firmware onto your ESP32 (Hub) and ESP8266 (Nodes).

### 2. Filesystem Setup

Upload the project files to the devices using a tool like Thonny or `ampy`.

**Hub (ESP32):**
*   `/hub/main.py` -> `/main.py`
*   `/hub/static/index.html` -> `/hub/static/index.html` (Ensure directory structure)
*   `/common/espnow_utils.py` -> `/common/espnow_utils.py`
*   `/libs/` -> Upload necessary libraries (`microdot`, `microdot_asyncio`, `microdot_websocket`)

**Node (ESP8266):**
*   `/node/main.py` -> `/main.py`
*   `/common/espnow_utils.py` -> `/common/espnow_utils.py`
*   `config.json` -> Create this file to set the Node ID.

### 3. Node Configuration
Create a `config.json` file on each Node to assign a unique ID:
```json
{
    "node_id": 1
}
```
*Change `node_id` to 2, 3, etc., for subsequent nodes.*

## Usage

1.  **Power On:** Turn on the Hub and all Nodes.
2.  **Connect:** On your phone or PC, connect to the WiFi Network:
    *   **SSID:** `Airsoft-Master`
    *   **Password:** *None (Open)*
3.  **Dashboard:** Open a browser and navigate to `http://192.168.4.1`.
4.  **Play:** Select a game mode (Time Attack or The Breach) from the dashboard to start.

## Development

### Project Structure
*   `hub/`: Code for the central controller (ESP32).
*   `node/`: Code for the individual targets (ESP8266).
*   `common/`: Shared utilities (ESP-NOW protocol).

### Protocol
*   **ESP-NOW:** Used for low-latency peer-to-peer communication.
*   **WebSocket:** Used for real-time updates between the Python backend and the HTML/JS frontend.

## License
[MIT License](LICENSE)
