import time
import math
import machine
import network
import espnow
from machine import Pin, ADC
import neopixel
import json
from common.espnow_utils import (pack_message, unpack_command, MSG_TYPE_HIT, MSG_TYPE_ANNOUNCE,
                                 CMD_SET_LED, CMD_SET_MODE, CMD_SET_ID, BROADCAST, WIFI_CHANNEL)

# --- Hardware Config (ESP8266 Wemos D1 Mini) ---
# GPIO 0 = D3 (Flash Button / LED)
# GPIO 5 = D1
# GPIO 4 = D2
SENSOR_PIN = 5      # D1 (Sensor)
LED_PIN = 0         # D3 (LED)
NUM_LEDS = 1

ANNOUNCE_MS = 5000      # heartbeat; the hub marks a node offline after ~15 s
BATTERY_READ_MS = 2000  # frequent ADC reads disturb the ESP8266 radio
SEND_RETRIES = 3

# --- Global State ---
NODE_ID = 0         # 0 = not assigned yet; the hub assigns one by MAC
hit_detected = False
last_hit_time = 0
last_announce_time = 0
SYSTEM_MODE = 0 # 0=Idle, 1=Active, 2=Standby
pulse_phase = 0.0
seq = 0
hub_mac = None      # learned from the first command the hub sends us
send_failures = 0
battery = (0.0, 0, False)
last_battery_read = 0
led_color = None

# --- Setup ---
led = neopixel.NeoPixel(Pin(LED_PIN), NUM_LEDS)
sensor = Pin(SENSOR_PIN, Pin.IN) # SW-420 usually needs no pull logic if module has op-amp
adc = ADC(0)

# Load Config (optional: an ID the hub assigned earlier, or one set by hand)
try:
    with open('config.json', 'r') as f:
        NODE_ID = json.load(f).get('node_id', 0)
        print(f"Loaded Config: Node {NODE_ID}")
except (OSError, ValueError):
    print("No config, hub will assign an ID")

e = None  # ESP-NOW, set up in setup_radio()

def setup_radio():
    global e
    # The ESP8266 starts an open AP by default; we don't want one per target
    network.WLAN(network.AP_IF).active(False)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(channel=WIFI_CHANNEL)
    e = espnow.ESPNow()
    e.active(True)
    try:
        e.add_peer(BROADCAST)
    except OSError:
        pass  # ESP8266 refuses (-3) but still sends to broadcast

# --- Interrupt Handler ---
def handle_hit(pin):
    global hit_detected, last_hit_time
    # Debounce 300ms
    now = time.ticks_ms()
    if time.ticks_diff(now, last_hit_time) > 300:
        hit_detected = True
        last_hit_time = now

sensor.irq(trigger=Pin.IRQ_RISING, handler=handle_hit)

# --- Helpers ---
def set_led(r, g, b):
    global led_color
    if led_color == (r, g, b):
        return
    led_color = (r, g, b)
    led[0] = led_color
    led.write()

def blink_led(r, g, b, duration=100):
    set_led(r, g, b)
    time.sleep_ms(duration)
    set_led(0, 0, 0)

def read_battery():
    # Helper to read battery voltage
    # Wemos D1 Mini internal divider puts 3.2V~ at 1024.
    # If using external divider for LiPo (4.2V), adjust factor.
    # Assuming standard Wemos divider + external:
    raw = adc.read()
    # Placeholder calibration: 1024 = 4.2V
    voltage = (raw / 1024.0) * 4.2

    # Calculate Percentage (Linear 3.0V - 4.2V)
    # 3.0V = 0%, 4.2V = 100%
    percent = int(((voltage - 3.0) / (4.2 - 3.0)) * 100)
    percent = max(0, min(100, percent))

    # Detect Charging
    # If voltage > 4.25V, likely charging?
    charging = (voltage > 4.25)

    return voltage, percent, charging

def battery_cached():
    global battery, last_battery_read
    now = time.ticks_ms()
    if last_battery_read == 0 or time.ticks_diff(now, last_battery_read) > BATTERY_READ_MS:
        battery = read_battery()
        last_battery_read = now
    return battery

def send(msg_type, hit=False):
    """Send to the hub. Unicast once we know the hub (ACKed + retried by the
    radio); broadcast before that, or as a last resort."""
    global seq, hub_mac, send_failures
    seq = (seq + 1) & 0xFFFF
    batt, pct, chg = battery_cached()
    msg = pack_message(NODE_ID, seq, batt, pct, msg_type, hit=hit, charging=chg)
    if hub_mac:
        for _ in range(SEND_RETRIES):
            try:
                if e.send(hub_mac, msg):
                    send_failures = 0
                    return True
            except OSError:
                pass
        send_failures += 1
        print(f"Hub did not ACK (x{send_failures})")
        if send_failures >= 3:
            # Hub gone or replaced: go back to broadcast until it talks to us
            hub_mac = None
    try:
        e.send(BROADCAST, msg)
    except OSError as ex:
        print(f"Broadcast failed: {ex}")
    return False

def save_node_id(new_id):
    global NODE_ID
    NODE_ID = new_id
    print(f"Hub assigned ID {new_id}")
    try:
        with open('config.json', 'w') as f:
            json.dump({'node_id': new_id}, f)
    except OSError as ex:
        print(f"Could not save config: {ex}")

def handle_command(host, msg):
    global hub_mac, SYSTEM_MODE
    cmd = unpack_command(msg)
    if not cmd:
        return  # e.g. another node's broadcast; not for us
    if host != hub_mac:
        hub_mac = host
        try:
            e.add_peer(host)
        except OSError:
            pass  # already a peer
        print("Hub found")
    cid, r, g, b = cmd
    if cid == CMD_SET_LED: # Set LED
        if not hit_detected and SYSTEM_MODE == 1:
            set_led(r, g, b)
    elif cid == CMD_SET_MODE:
        if SYSTEM_MODE != r:
            print(f"CMD MODE: {r}")
        SYSTEM_MODE = r
        # Reset LED on mode change
        set_led(0, 0, 0)
    elif cid == CMD_SET_ID:
        if r and r != NODE_ID:
            save_node_id(r)

# --- Main Loop ---
def loop_once():
    global hit_detected, last_announce_time, pulse_phase

    # Periodic Announce (Every 5s): heartbeat so the hub knows we're alive
    now = time.ticks_ms()
    if time.ticks_diff(now, last_announce_time) > ANNOUNCE_MS:
        send(MSG_TYPE_ANNOUNCE)
        last_announce_time = now

    # Check for incoming commands (Hub -> Node)
    while e.any():
        host, msg = e.recv(0)
        if msg:
            handle_command(host, msg)

    # --- Mode Logic ---
    if SYSTEM_MODE == 0: # Idle
        # Dim Blue or Pulse Blue if Low Batt
        if battery_cached()[1] < 10:
            # Pulse: Range 0-50 Blue, approx 1Hz
            pulse_phase += 0.1
            set_led(0, 0, int((math.sin(pulse_phase) + 1) * 25))
        else:
            set_led(0, 0, 10) # Static Dim Blue 10/255

    elif SYSTEM_MODE == 2: # Standby
        set_led(0, 0, 0)

    # --- Hit Logic ---
    if hit_detected:
        print("HIT!")
        # Send Data (Always send for diagnostics)
        send(MSG_TYPE_HIT, hit=True)

        # Visual Feedback (ONLY if Active)
        if SYSTEM_MODE == 1:
            blink_led(255, 255, 255, 100) # Flash White, then off
        hit_detected = False

def main():
    global last_announce_time
    setup_radio()
    print(f"Airsoft Node {NODE_ID} (ESP8266) Started")
    set_led(0, 0, 10)
    # Announce on the first pass instead of 5 s after boot
    last_announce_time = time.ticks_add(time.ticks_ms(), -ANNOUNCE_MS - 1)
    errors = 0
    while True:
        try:
            loop_once()
            errors = 0
        except Exception as ex:
            errors += 1
            print(f"Loop error ({errors}): {ex}")
            if errors >= 20:
                machine.reset()  # keep failing: start clean
        time.sleep_ms(10)

if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        # Outside the guarded loop: reboot rather than sit at the REPL.
        # Ctrl-C (KeyboardInterrupt) is not an Exception, so mpremote still works.
        print(f"Fatal: {ex}")
        time.sleep(3)
        machine.reset()
