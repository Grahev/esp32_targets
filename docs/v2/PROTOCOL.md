# Radio protocol v3

The source of truth is `firmware/shared/src/protocol.h`; this page is a summary.

Transport: ESP-NOW, one frame per packet (≤ 250 bytes), on the hub's WiFi channel. Little-endian, packed.

**Header (8 bytes):** `magic 0xA7 | version 3 | system_id u16 | type u8 | node_id (slot) u8 | seq u16`.
- `system_id` is random per hub. Nodes send 0 while unpaired; the hub drops frames from other systems.
- `seq` increases per sender. The hub drops a repeated `(mac, seq)` within 2 s (radio retries).

| Type | Dir | Payload | Notes |
|---|---|---|---|
| 0x01 Hello | N→H | fw x.y.z, hw_rev, caps, led_pin, battery mV/%, flags | broadcast while searching (3 per channel, 250 ms apart, channels 1–13), unicast while waiting to be added |
| 0x02 Heartbeat | N→H | battery mV/%, flags, mode, effect_id, uptime | every 2 s; answered by HubAck |
| 0x03 Hit | N→H | reaction_ms (0xFFFF = not lit), effect_id, edges, hit_count, uptime_ms | unicast, 3 attempts |
| 0x04 Ack | N→H | acked type + seq, status, value | answers SetMode, Config, Identify, Channel, Ota*, Reboot |
| 0x81 Welcome | H→N | slot, accepted, channel, hb interval, mode | answer to Hello |
| 0x82 SetMode | H→N | Idle 0 / Active 1 / Standby 2 / Calibrate 3 | ACKed, retried |
| 0x83 Led | H→N | effect, r, g, b, p1, p2, effect_id | Off, Solid, Blink(period,count), Pulse(period), Flash(ms), Ramp(ms,from); same id = no restart; re-sent every 2 s while lit |
| 0x84 Config | H→N | list of key/value (u8/u16) | brightness, debounce, glitch edges/window, battery scale, heartbeat, hit flash, LED pin |
| 0x85 Identify | H→N | seconds | white blink |
| 0x86 Channel | H→N | channel, switch_in_ms | before the hub moves channel |
| 0x87–0x89 OtaBegin/Data/End | H→N | size + MD5 / offset + ≤200 bytes / – | stop-and-wait; the node ACKs the next offset; MD5 checked before reboot |
| 0x8A Reboot, 0x8B Forget | H→N | – | Forget unpairs the node |
| 0x8C HubAck | H→N | as Ack | answer to Heartbeat |

**Link rules:** a node that misses 4 heartbeat answers, or 3 frames in a row that the radio couldn't deliver, goes back to searching. The hub marks a node offline after `3 × heartbeat + 1.5 s` of silence, or after 2 failed unicasts in a row.
