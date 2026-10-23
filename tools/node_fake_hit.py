"""Runs ON A NODE: fake sensor hits through the real node code and radio.

  timeout 60 mpremote connect $NODE run tools/node_fake_hit.py

Imports node main.py without starting its loop, waits until the hub has
talked to us, then sets the IRQ flag a few times as if the sensor fired.
Reset the node afterwards.
"""
import time
import main as node

HITS = 5
GAP_MS = 2500

node.setup_radio()
node.last_announce_time = time.ticks_add(time.ticks_ms(), -node.ANNOUNCE_MS - 1)
t0 = time.ticks_ms()
while node.hub_mac is None and time.ticks_diff(time.ticks_ms(), t0) < 15000:
    node.loop_once()
    time.sleep_ms(10)
print('N> hub', node.hub_mac, 'mode', node.SYSTEM_MODE, 'id', node.NODE_ID)

for i in range(HITS):
    t = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t) < GAP_MS:
        node.loop_once()
        time.sleep_ms(10)
    node.hit_detected = True
    node.loop_once()
    print('N> hit', i + 1, 'seq', node.seq, 'send_failures', node.send_failures, 'led', node.led_color)
print('N> done')
