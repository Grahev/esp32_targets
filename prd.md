PRD: IoT Airsoft Target System (v1.3)1. Project OverviewA low-latency, modular airsoft target system. Multiple "Target Nodes" detect hits and communicate via ESP-NOW to a "Central Hub." The Hub hosts a Web Dashboard for real-time scoring and game management.2. Hardware Specification2.1 Target Node (ESP32-S2 Mini)MCU: ESP32-S2 Mini (Single-core).Vibration Sensor: SW-420 (Digital) on GPIO 1 (D01).Feedback: 1x WS2812B RGB LED on GPIO 3 (D03) (Expandable).Input: Built-in Boot Button on GPIO 0 (Used for Pairing/Reset).Power: USB 5V (Current) / Battery Shield (Future).2.2 Central Hub (ESP32-S2 Mini)Role: ESP-NOW Receiver + Wi-Fi Access Point + Web Server.Storage: LittleFS for scores.json and config.json.3. Communication Protocol (ESP-NOW)To ensure <50ms latency, the system uses ESP-NOW.Payload Structure (JSON or Struct):C++struct Message {
  int targetID;      // Unique ID for the node
  float battery;     // Battery voltage (placeholder for now)
  bool hitDetected;  // Trigger flag
} 
4. Software Requirements4.1 Target Node LogicInterrupt Handling: Use attachInterrupt() on GPIO 1 (RISING edge) for the SW-420.Debounce: Implement a software lockout of 300ms after a hit is detected.Pairing Mode: * On long-press of GPIO 0 (>3s), enter "Pairing Mode" (LED Blinks Blue).Save Hub MAC address to NVS (Non-Volatile Storage).LED States:Idle: Dim Green breathing.Hit: Instant White flash (100ms).Target Active: Solid Red (Game specific).4.2 Hub & Web Dashboard LogicNetwork: Create an Access Point named Airsoft-Master (No password).Web Server: Use ESPAsyncWebServer.WebSockets: Send real-time "Hit" events to the browser.Frontend Features:Dashboard: Displays "Total Hits" and "Last Hit Time."Game Modes:
Time Attack: User hits 3 targets; clock stops.
Zombie: 
    - Survival Mode with Waves.
    - Target accumulates brightness ("gradual start").
    - If full brightness reached without hit = Player "bitten" (Game Over).
    - Waves get harder (faster ramp-up).
Memory Patterns: 
    - Standard: "Simon Says" style. Pattern grows by one each round (A -> A,B -> A,B,C).
    - Hard: Pattern length increases but changes completely each round (A -> B,C -> D,A,C).
    - Rules: Hit in correct order. Mistake = Game Over. Time is recorded for tie-breaking.
Settings: Slider to adjust Cooldown (ms) and LED Brightness.4.3 Data PersistenceStore scores.json in LittleFS.Format: {"user": "Player1", "mode": "TimeAttack", "score": 12.5, "date": "2026-01-07"}.
7. Documentation
User Manual: Step-by-step guide to power on, pair nodes, and use the dashboard.
Setup Guide: Instructions for flashing firmware to ESP32-S2 (using esptool/mpremote) and initial system configuration.5. Development MilestonesPhaseFocusKey TaskPhase 1Node FirmwareCode for D01 Interrupts and D03 LED feedback.Phase 2ConnectivityEstablish ESP-NOW link between Node and Hub.Phase 3Web InterfaceBuild the HTML/JS dashboard with WebSockets.Phase 4Game LogicProgram the Time Attack and Zombie logic.6. Constraints & Safety
LED Power: Limit brightness to 150/255 global max (Zombie mode scales to this limit).
Latency: No blocking delay() calls.
Hardware Limits:
    - **Max Targets**: 8 Nodes (V1).
    - **WiFi Channel**: Fixed to Channel 1 (Node & Hub must match).
    - **Sensor Failsafe**: Ignore signals >500ms (prevent stuck sensor scoring).