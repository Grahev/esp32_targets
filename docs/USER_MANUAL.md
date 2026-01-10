# Airsoft Gemini - User Manual

## 1. Hardware Overview
- **Target Node**: The sensor unit. Detects BB hits and lights up.
    - **LED**: 
        - **Green Breathing**: Idle/Ready.
        - **White Flash**: Hit Detected.
        - **Red**: Active Target (Shoot me!).
    - **Button**: 
        - Single Press: Reset/Reboot.
        - Long Press (Future): Pairing Mode.
- **Central Hub**: The commander. Hosts the WiFi game server.

## 2. Getting Started
1. **Power On**: Connect all **Target Nodes** and the **Control Hub** to USB power.
2. **Connect WiFi**:
    - On your phone/laptop, search for WiFi named `Airsoft-Master`.
    - Connect (No password required).
3. **Open Dashboard**:
    - Open a web browser (Chrome/Safari).
    - Go to `http://192.168.4.1`.
    - You should see the "Gemini Dashboard".
4. **Sync Nodes (Crucial Step)**:
    - Tap each Target Node once.
    - The Node will flash white, and the Hub will register its address.
    - **Why?** The Hub needs to learn where to send LED commands.

## 3. Game Modes

### Time Attack
- **Goal**: Hit 3 targets as fast as possible.
- **Flow**: Targets light up Red. Timer starts. Clock stops when all 3 are hit.

### Zombie Survival
- **Goal**: Survive the waves!
- **Flow**:
    - Targets will slowly fade in (Red).
    - **Shoot it** before it gets fully bright!
    - **Wave 1**: Slow.
    - **Wave 2+**: Faster and faster.
    - If a target reaches max brightness -> **YOU ARE BITTEN**. Game Over.

### Memory Patterns ("Simon Says")
- **Standard**: Watch the sequence (e.g., A -> B). Repeat it by shooting A then B. Sequence grows longer (+1 each round).
- **Hard**: Sequence changes completely each round (Random).
- **Mistake**: Hitting wrong target = Game Over.

## 4. Troubleshooting
- **Node not registering hits?**
    - Check if LED is Green (Idle).
    - Ensure Hub is powered on first.
    - Move Node closer to Hub (range ~50m).
- **Dashboard not loading?**
    - Reconnect to `Airsoft-Master` WiFi.
    - Refresh page.
