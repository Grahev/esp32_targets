# Airsoft Gemini - Setup & Flashing Guide

## 1. Prerequisites
- **Python 3.x** installed.
- **MicroPython Firmware**: Download `esp32s2-20230426-v1.20.0.bin` (or newer) from [micropython.org](https://micropython.org/download/esp32s2/).
- **Tools**: Install `esptool` and `mpremote`:
  ```bash
  pip install esptool mpremote
  ```

## 2. Flashing MicroPython

### Hub (ESP32-S2)
1. Erase Flash: `esptool.py --chip esp32s2 --port COMx erase_flash`
2. Flash Firmware: `esptool.py --chip esp32s2 --port COMx write_flash -z 0x1000 esp32s2-v1.20.0.bin`

### Target Node (ESP8266 D1 Mini)
1. Erase Flash: `esptool.py --chip esp8266 --port COMy erase_flash`
2. Flash Firmware: `esptool.py --chip esp8266 --port COMy write_flash --flash_size=detect 0 esp8266-20230426-v1.20.0.bin`
   *(Get ESP8266 firmware from micropython.org)*

## 3. Uploading Code

### Option A: Using `mpremote` (Recommended)

#### 3.1 Flash the HUB
The Hub requires the web server libraries and the game engine.
Run these commands from the project root (`Airsoft Gemini/`):

1. **Connect Hub ESP32** via USB.
2. Upload Shared Code:
   ```bash
   mpremote cp -r common :
   ```
3. Upload Libraries:
   ```bash
   # Create lib dir
   mpremote exec "import os; os.mkdir('lib')"
   # Upload libraries
   mpremote cp hub/lib/microdot.py :lib/microdot.py
   mpremote cp hub/lib/microdot_asyncio.py :lib/microdot_asyncio.py
   mpremote cp hub/lib/microdot_websocket.py :lib/microdot_websocket.py
   ```
4. Upload Hub Code:
   ```bash
   mpremote cp hub/game_engine.py :
   mpremote cp hub/main.py :main.py
   ```
   *Note: We rename `hub/main.py` to `main.py` on the device so it runs on boot.*
5. Upload Web Files:
   ```bash
   mpremote exec "import os; os.mkdir('hub'); os.mkdir('hub/static')"
   mpremote cp hub/static/index.html :hub/static/index.html
   ```

#### 3.2 Flash a TARGET NODE
1. **Connect Node ESP32** via USB.
2. Upload Shared Code:
   ```bash
   mpremote cp -r common :
   ```
3. Upload Node Code:
   ```bash
   mpremote cp node/main.py :main.py
   ```

### Option B: Using Thonny IDE (Visual)
Great for beginners.

**Initial Setup**:
1. Open Thonny.
2. Go to **Tools** > **Options** > **Interpreter**.
3. Select **MicroPython (ESP32)** and the correct Port.
4. Go to **View** > **Files**. You will see "Local files" (top) and "MicroPython device" (bottom).

**Uploading to HUB**:
1. In "Local files", navigate to the project folder.
2. Right-click the `common` folder -> **Upload to /**.
3. Create folders on Device:
   - Right-click inside "MicroPython device" -> **New directory...** -> name it `lib`.
   - Create another directory named `hub`.
   - Inside `hub`, create `static`.
4. Upload Files:
   - Go to `hub/lib/` (Local) -> Select all files -> Right-click **Upload to /lib**.
   - Upload `hub/game_engine.py` -> **Upload to /**.
   - Open `hub/main.py` in the editor -> **File > Save as...** -> **MicroPython device** -> save as `main.py` (Overwrite if asked).
   - Go to `hub/static/` (Local) -> Upload `index.html` to `/hub/static/`.

**Uploading to TARGET NODE**:
1. Right-click `common` -> **Upload to /**.
2. Open `node/main.py` in editor -> **File > Save as...** -> **MicroPython device** -> save as `main.py`.

## 4. Verification
1. **Power up Hub**. Wait for LED (if config) or check WiFi `Airsoft-Master`.
2. **Power up Node**. It should blink Green (Idle).
3. Tap Node sensor -> Node blinks White. Hub prints "HIT" in Serial terminal.
4. Open `192.168.4.1` on WiFi to see Dashboard.
