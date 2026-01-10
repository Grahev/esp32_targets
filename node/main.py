import time
import machine
import network
import espnow
from machine import Pin
import neopixel
from common.espnow_utils import init_espnow, pack_message

# --- Hardware Config (ESP8266 Wemos D1 Mini) ---
# GPIO 0 = D3 (Flash Button / LED)
# GPIO 5 = D1
# GPIO 4 = D2
ID_PIN = -1         # Disabled, was 0
SENSOR_PIN = 5      # D1 (Sensor)
LED_PIN = 0         # D3 (LED)
NUM_LEDS = 1

# --- Global State ---
NODE_ID = 1         
hit_detected = False
last_hit_time = 0

# --- Setup ---
led = neopixel.NeoPixel(Pin(LED_PIN), NUM_LEDS)
sensor = Pin(SENSOR_PIN, Pin.IN) # SW-420 usually needs no pull logic if module has op-amp

# Initialize WiFi for ESP-NOW (Station Mode required for ESP8266)
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(channel=1) # Same as Hub
e = espnow.ESPNow()
e.active(True)

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
    print(f"Airsoft Node {NODE_ID} (ESP8266) Started")
    # Peer with Hub (Broadcast usually works on ESP8266 too, but explicit mac preferred if issues)
    peer = b'\xff' * 6
    try:
        e.add_peer(peer)
    except OSError:
        pass 

    set_led(0, 10, 0) # Idle Green
    
    from common.espnow_utils import unpack_command

    while True:
        global hit_detected
        
        # Check for incoming commands (Hub -> Node)
        if e.any():
            host, msg = e.recv()
            if msg:
                print(f"RX {len(msg)}b from {host}")
                cmd = unpack_command(msg)
                if cmd:
                    cid, r, g, b = cmd
                    if cid == 1: # Set LED
                         print(f"CMD LED: {r},{g},{b}") 
                         if not hit_detected: 
                            set_led(r, g, b)
                else:
                    print(f"Unpack fail: {msg}")

        if hit_detected:
            print("HIT!")
            # 1. Visual Feedback
            blink_led(255, 255, 255, 100) # Flash White
            
            # 2. Send Data
            # Battery check is manual on ESP8266 (A0), ignored for now (sent as 3.3)
            msg = pack_message(NODE_ID, 3.3, True)
            try:
                e.send(peer, msg)
            except Exception as ex:
                print("Send failed")
            
            hit_detected = False
            # Return to 'off' or wait for next command? 
            # Ideally return to last known state, but for now black/idle
            set_led(0, 0, 0) 

        time.sleep_ms(10)

if __name__ == "__main__":
    main()
