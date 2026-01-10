import time
import machine
from machine import Pin
import neopixel
from common.espnow_utils import init_espnow, pack_message

# --- Hardware Config ---
ID_PIN = 0          # GPIO 0 (Boot button)
SENSOR_PIN = 1      # GPIO 1 (Vibration Sensor)
LED_PIN = 3         # GPIO 3 (WS2812B)
NUM_LEDS = 1
BAT_PIN = 2         # ADC Pin for battery (Example)

# --- Global State ---
NODE_ID = 1         # Default ID, should be loaded from NVS later
hit_detected = False
last_hit_time = 0

# --- Setup ---
led = neopixel.NeoPixel(Pin(LED_PIN), NUM_LEDS)
sensor = Pin(SENSOR_PIN, Pin.IN) # SW-420 often needs a pull-down or pull-up depending on module
# Note: SW-420 is digital. Rising edge usually means vibration start.

e, wlan = init_espnow(mode=machine.WLAN.STA_IF)

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
    led[0] = (r, g, b)
    led.write()

def blink_led(r, g, b, duration=100):
    set_led(r, g, b)
    time.sleep_ms(duration)
    set_led(0, 0, 0)

# --- Main Loop ---
def main():
    print(f"Airsoft Node {NODE_ID} Started")
    # Peer with broadcast or specific hub MAC (Broadcast for now)
    peer = b'\xff' * 6
    try:
        e.add_peer(peer)
    except OSError:
        pass # Already exists

    set_led(0, 10, 0) # Idle Green

    while True:
        global hit_detected
        
        if hit_detected:
            print("HIT!")
            # 1. Visual Feedback
            blink_led(255, 255, 255, 100) # Flash White
            
            # 2. Send Data
            msg = pack_message(NODE_ID, 4.2, True)
            try:
                e.send(peer, msg)
            except Exception as ex:
                print("Send failed:", ex)
            
            hit_detected = False
            set_led(0, 10, 0) # Back to Idle

        time.sleep_ms(10)

if __name__ == "__main__":
    main()
