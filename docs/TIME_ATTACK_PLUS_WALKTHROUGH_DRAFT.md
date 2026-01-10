# Time Attack+ Walkthrough (DRAFT)

This document outlines the intended user experience and behavior for the Time Attack+ mode.

## 1. Setup Phase
1.  **Access Dashboard**: User opens the Hub Web UI.
2.  **Select Mode**: Chooses "Time Attack+" from the dropdown.
3.  **Configuration**:
    - **Duration**: Selects "1 Min".
    - **Difficulty**: Selects "Hard".
    - **Penalties**: Checks "Enabled".
    - **Parameters**: Leaves "Respawn Delay" at default (1.0s).
4.  **Start**: User clicks "START GAME".

## 2. Start Sequence (The "Psych Up")
1.  **Pulsing (0-1.5s)**: All nodes pulse Orange 3 times. Warning sound (if audio supported) or visual rhythm.
2.  **Ready (1.5s-2.3s)**: All nodes blink Green ONCE distinctively.
3.  **GO (2.3s)**:
    - Timer starts at 1:00.
    - Application logs "Game Started - Hard Mode".
    - **Initial Spawns**: Since Hard Mode starts with Min 2 targets, two random nodes turn RED immediately.

## 3. Gameplay Loop (The "Flow")
### Stage 0 (0-20s): Warm-up
- Player hits Node A (RT: 300ms).
    - **Score**: +1 Hit, ~+2 RT Bonus.
    - **Combo**: 1.
    - Node A turns OFF.
- Player hits Node B (RT: 500ms).
    - **Score**: +1 Hit, +1 RT Bonus.
    - **Combo**: 2.
    - Node B turns OFF.
- **Respawn**: Nodes reappear after ~1.0s (Base).

### Stage 1 (20-40s): Ramp-up
- **Intensity Increases**: Respawn delay drops (~0.8s).
- **Spawn Logic**: System prioritizes Node C and D if they haven't been used.
- Player hits Node C (RT: 200ms).
    - **Score**: +1 Hit, +3 RT Bonus.
    - **Combo**: reaches 5 -> **+5 Bonus Points**.

### Stage 3 (60s+): Climax (if Duration > 1m)
- If this were a 2m game, by 60s:
    - Minimum active targets increases to 3.
    - Respawn capability becomes extremely fast (0.35s).
    - Player must rely on peripheral vision.

### Event: The "Combo Breaker"
- Player anticipates Node A spawning but hits inactive Node D by mistake.
    - **Penalty**: -2 Points (Hard Mode).
    - **Combo**: Resets to 0.
    - Flashing Red feedback on dashboard.

## 4. Game End
1.  **Timer hits 0:00**.
2.  **Cooldown**: All nodes turn **Solid Blue**.
3.  **Dissolve**: After 10s, Blue fades to Black over 3s.
4.  **Results**: Dashboard shows:
    - "Rank: Elite Operator"
    - "Total Score: 450"
    - "Max Combo: 15"
    - "Avg Reaction: 420ms"

## 5. Leaderboard Update
- The system saves the score to `scores_time_attack_plus.json`.
- The Leaderboard table refreshes, showing this run in the "Hard / 1 Min" category.
