# Time Attack+ Mode – Feature PRD

## 1. Overview
Time Attack+ is an enhanced, skill-based competitive mode where players try to hit as many active targets as possible before the timer expires. The mode reduces randomness, introduces dynamic difficulty scaling, uses reaction-time scoring, penalizes inaccurate hits, and supports scalable node counts (2–5).

At the end of a match, all nodes turn Blue for 10 seconds, then slowly dim off to avoid leaving LEDs energized unnecessarily.

## 2. System Requirements & Constraints
- **Minimum nodes**: 2
- **Maximum nodes**: 5
- Modes must function with any number within that range
- No pattern activation systems (no sweeps, waves, clusters)
- Only controlled random + fairness-driven spawn logic
- Node hardware does not support enhanced effects beyond LEDs

## 3. User Flow

### 3.1 Configuration Screen (UI)
**Settings:**
*   **Basic Settings**
    *   Game Duration: 1, 2, or 5 minutes
    *   Difficulty Level: Easy, Normal, Hard, Extreme
*   **Spawn Behavior**
    *   Respawn Delay Max (seconds): configurable (default 1.0s)
    *   Minimum Active Targets:
        *   Easy: 1
        *   Normal: 1–2
        *   Hard: 2–3
        *   Extreme: 3–4
*   **Penalties**: On/Off (Hitting inactive node applies scoring penalty)
*   **Scoring Enhancements**
    *   Reaction-time bonuses enabled by default
    *   Combo system enabled by default

## 4. Game Start Sequence
1.  Orange pulse on all nodes (3 pulses)
2.  Green blink (1 blink)
3.  Game timer begins
4.  Node activation begins based on spawn scheduler and difficulty

## 5. Gameplay Systems

### 5.1 Node Activation
Nodes activate based on:
1.  Controlled pseudo-random selection
2.  Fairness weighting (underused nodes more likely to activate)
3.  Minimum active target enforcement
4.  Difficulty scaling

**Activation Rules:**
*   Active node = Red
*   Inactive = Off
*   Hit only counts when node is red
*   When hit: Node turns off, Respawns after random delay (capped by difficulty & intensity)

### 5.2 Controlled RNG (Reduced Randomness)
Instead of pure randomness:
*   **Scheduler ensures fair distribution**
*   No more than 2 consecutive activations on same node
*   Weighted selection favors nodes rarely used recently
*   Always maintains minimum active targets to prevent dead time

### 5.3 Dynamic Difficulty Scaling
Difficulty increases automatically during gameplay unless player selected “Static Difficulty”.

**Intensity Stages:**
*   Stage 0: 0s–20s
*   Stage 1: 20s–40s
*   Stage 2: 40s–60s
*   Stage 3: 60s–80s
*   Stage 4: 80s–100s
*   Stage 5: 100s+ (final moments)

**Scaling Parameters:**
*   Activation speed
*   Respawn delay reduction
*   Increased minimum active nodes
*   Combo multiplier adjusts
*   Reaction time bonus increases at higher intensity

### 5.4 Reaction-Time Scoring
When a node goes red, timestamp is recorded.
**Reaction time** = time from activation → valid hit

**Bonus Rules:**
| Reaction Time | Bonus |
| :--- | :--- |
| ≤ 600ms | +3 |
| 601–900ms | +2 |
| 901–1400ms | +1 |
| > 1400ms | +0 |

### 5.5 Penalties (Optional)
If enabled, hitting inactive node = penalty.

| Difficulty | Penalty |
| :--- | :--- |
| Easy | -1 |
| Normal | -1 |
| Hard | -2 |
| Extreme | -5 |

### 5.6 Combo System
*   Consecutive successful hits (no penalties) increase combo count
*   Every 5 consecutive hits = +5 bonus score
*   **Combo resets on**: Penalty OR Reaction time > 1000ms (slow response)

## 6. Game End Sequence
When timer reaches 0:
1.  All nodes switch to **Blue**
2.  Stay on Blue for 10 seconds
3.  LEDs begin a slow fade-out sequence over several seconds
4.  Enter idle/off state

## 7. Results Screen
Shown immediately after game-end fade-out.

**Displayed Stats:**
*   Total Score
*   Total Hits
*   Penalties
*   Max Combo
*   Avg Reaction Time
*   Difficulty Level
*   Duration

**Score breakdown:** Hits, RT bonuses, Combo bonuses, Penalties

## 8. Leaderboard & Progression

### 8.1 Leaderboards
Separate leaderboards by:
*   Difficulty (Easy/Normal/Hard/Extreme)
*   Duration (1/2/5 min)

**Score fields:** Rank | Score | Hits | Avg RT | Max Combo | Penalties | Date

### 8.2 Personal Progression
Local progression profile:
*   Personal Best per difficulty
*   Personal Best RT
*   Highest combo achieved
*   **Player achievement titles**: Shooter I–V, Marksman I–V, Elite Operator, Grandmaster

### 8.3 Seasonal Leaderboards
Optional reset cycles: Weekly, Monthly

## 9. Optional Mode Variants
*   **Time Frenzy**: 30–60s duration, extremely fast spawns.
*   **Endurance**: Continue until hit inactive target or exceed slow RT threshold 3 times.
*   **Precision Mode**: Only one active node, higher penalties.

## 10. Spawn Scheduling Logic (Technical)

### 10.1 Core Loop (Pseudocode)
```python
Every 50ms:
    update_intensity_stage()
    if active_nodes.count < min_active_targets:
         spawn_nodes(min_active_targets - active_nodes.count)

    if time_since(last_spawn) >= computed_cooldown:
         run_weighted_spawn()
         last_spawn = now
```

### 10.2 Weighted Spawn System
```python
available = nodes NOT in active_nodes
weights[node] = MAX_WEIGHT - spawn_history[node]
chosen = weighted_random_choice(available, weights)
activate_node(chosen)
spawn_history[chosen]++
```

### 10.3 Respawn Logic
```python
on hit(node):
    deactivate_node(node)
    after random(0.1, respawn_delay_max_scaled):
         activate_node(node)
```

### 10.4 Difficulty-Based Cooldown
```python
base = respawn_delay_max
cooldown = base * (1 - intensity_stage * 0.1)
difficulty modifier: Easy(x1.0), Normal(x0.8), Hard(x0.6), Extreme(x0.4)
```

## 11. Difficulty Curves
**Activation Speed Curve**
| Stage | Easy | Normal | Hard | Extreme |
| :--- | :--- | :--- | :--- | :--- |
| S0 (0s) | 1.0 | 0.8 | 0.5 | 0.35 |
| S1 (20s) | 0.95 | 0.70 | 0.45 | 0.30 |
| S2 (40s) | 0.90 | 0.60 | 0.40 | 0.25 |
| S3 (60s) | 0.85 | 0.55 | 0.35 | 0.20 |
| S4 (80s) | 0.80 | 0.50 | 0.30 | 0.15 |
| S5 (100s) | 0.75 | 0.45 | 0.25 | 0.12 |

**Minimum Active Target Curve**
| Stage | Easy | Normal | Hard | Extreme |
| :--- | :--- | :--- | :--- | :--- |
| S0 | 1 | 1 | 2 | 2 |
| S2 | 1 | 2 | 3 | 3 |
| S4 | 1 | 2 | 3 | 4 |
| S5 | 2 | 3 | 3 | 4 |

## 12. Persistence
Stored in `scores_time_attack_plus.json`.
```json
{
  "date": "2026-01-01",
  "score": 237,
  "hits": 62,
  "penalties": 4,
  "avg_reaction_ms": 348,
  "combo_max": 12,
  "difficulty": "Hard",
  "duration_min": 1,
  "variant": "Standard"
}
```
