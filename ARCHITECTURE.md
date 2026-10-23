# Architecture

One **hub** (ESP32) runs the game and the web dashboard. N **nodes** (ESP8266 Wemos D1 Mini) are targets. They talk over ESP-NOW on WiFi channel 1. Phones and laptops join the hub's open AP `Airsoft-Master` and use the dashboard at http://192.168.4.1.

```mermaid
flowchart LR
    subgraph Players
        B1[Phone / laptop browser]
    end
    subgraph HUB["HUB — ESP32 (main.py)"]
        WEB[Microdot HTTP :80<br>/ /start /stop /api/leaderboard]
        WS[WebSocket /ws]
        L[espnow_listener]
        G[game_loop → GameMode.tick 100 ms]
        R[(node registry<br>id → MAC, battery, last seen)]
        F[(scores_*.json)]
    end
    subgraph NODES["NODES 1..N — ESP8266 (node/main.py)"]
        N1[Node: SW-420 sensor + WS2812 LED + battery ADC]
        N2[Node ...]
    end

    B1 -- "HTTP: start/stop" --> WEB
    WS -- "status / hit / score / timer / battery / leaderboard / nodes" --> B1
    N1 -- "ESP-NOW: ANNOUNCE/heartbeat, HIT" --> L
    N2 -- "ESP-NOW" --> L
    L --> R
    L -- "on_hit(node_id)" --> G
    G -- "ESP-NOW: SET_LED, SET_MODE" --> N1
    G -- "ESP-NOW" --> N2
    G -- "game over" --> F
```

## Message flow

```mermaid
sequenceDiagram
    participant N as Node
    participant H as Hub
    participant UI as Browser
    N->>H: ANNOUNCE (id, battery) — at boot, then every few seconds
    H->>N: SET_MODE (current mode)
    H->>UI: battery / nodes
    UI->>H: GET /start?mode=TimeAttack
    H->>N: SET_MODE 1 (Active)
    H->>N: SET_LED red (this node is a target)
    N->>H: HIT (sensor IRQ)
    H->>N: SET_LED off
    H->>UI: score, hit
    H->>N: SET_MODE 2 (Standby) → 10 s → SET_MODE 0 (Idle)
```

## Files

| Area | Repo file | Runs on |
|------|-----------|---------|
| Protocol (struct formats, constants) | `common/espnow_utils.py` | hub + node |
| Hub entry, radio, web server, scores | `hub/main.py` | hub (as `:main.py`) |
| Game modes | `hub/game_engine.py` | hub |
| Dashboard | `hub/static/index.html` | browser, served by hub |
| Web framework | `hub/lib/microdot*.py` | hub `:lib/` |
| Node firmware | `node/main.py` | each node (as `:main.py`) |

See CLAUDE.md "How the project works" for the packet layout and the mode values.
