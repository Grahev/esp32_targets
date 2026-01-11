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
    *   Game Duration: 1 Minute (Standard)
    *   Difficulty/Distance: Normal
*   **Spawn Behavior**
    *   Anti-Spam Logic: Always Enabled
    *   Minimum Active Targets: 1 (Stage 0-1), up to 2 (Stage 2 end)
*   **Penalties**: High Weight (Freeze + Points)

## 4. Game Start Sequence
1.  **Pulsing (0-1.5s)**: Yellow pulse on all nodes (3 pulses)
2.  **Ready (1.5s-2.3s)**: Green blink (1 blink)
3.  **GO (2.3s)**:
    *   Timer starts at 1:00
    *   Initial Spawn: 1 Node Red

## 5. Gameplay Systems

### 5.1 Node Activation
Nodes activate based on:
1.  Controlled pseudo-random selection
2.  **No-Repeat Rule**: Next node cannot be the one just hit.

**Activation Rules:**
*   Active node = Red
*   Inactive = Off
*   Hit only counts when node is red
*   **150ms Global Input Mask** after valid hit.

### 5.2 Dynamic Difficulty Scaling
**Intensity Stages:**
*   **Stage 0 (0s–30s)**: Warm-up. Spawn Delay 1.2s.
*   **Stage 1 (31s–50s)**: Ramp-up. Spawn Delay 0.8s. Combo Multipliers active.
*   **Stage 2 (51s–60s)**: Blitz. Spawn Delay 0.5s. Last 5s may actuate 2 simultaneous targets.

### 5.3 Reaction-Time Scoring
When a node goes red, timestamp is recorded.
**Reaction time** = time from activation → valid hit

**Bonus Rules (Revised):**
| Reaction Time | Bonus | Description |
| :--- | :--- | :--- |
| < 750ms | +10 | Elite |
| 750–1400ms | +5 | Standard |
| > 1400ms | +2 | Slow |

### 5.4 Penalties (The "Freeze")
Trigger: Hitting an Inactive (Dark) node.
*   **Score Penalty**: -15 Points.
*   **The Freeze**: All nodes flash **ORANGE** for 1.0 second.
*   **Effect**: No targets spawn during freeze. Timer continues.

### 5.5 Combo System
*   Every 3 consecutive successful hits (no penalties): **1.5x Multiplier** on subsequent points.
*   Multiplier resets on Penalty.

## 6. Game End Sequence
When timer reaches 0:00:
1.  **Cooldown**: All nodes turn **Solid Blue**.
2.  **Dissolve**: After 10s, Blue fades to Black over 3s. Nodes stop registering hits.

## 7. Results Screen
**Displayed Stats:**
*   Rank (e.g., "Sharpshooter")
*   Total Score
*   Precision Rate (Successful Hits / Total Shots)
*   Spam Penalties (Count of Freezes)
*   Avg Reaction Time

## 8. Persistence
Stored in `scores_time_attack_plus.json`.
Highlight "Precision Rate" on leaderboards.
