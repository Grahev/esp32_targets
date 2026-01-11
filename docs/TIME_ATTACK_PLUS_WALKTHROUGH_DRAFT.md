# Time Attack+ Walkthrough (REVISED)

This document outlines the professional-grade behavior for the Time Attack+ mode, optimized for airsoft reaction times and trigger discipline.

## 1. Setup Phase
1.  **Access Dashboard**: User opens the Hub Web UI.
2.  **Select Mode**: Chooses "Time Attack+" from the dropdown.
3.  **Configuration**:
    - **Duration**: 1 Min (Standard).
    - **Difficulty/Distance**: Selects "Normal" (scaling for 10–15m).
    - **Anti-Spam Logic**: ALWAYS ENABLED (Single-target activation only).
    - **Penalty Weight**: High (Freeze + Point Deduction).
4.  **Start**: User clicks "START GAME".

## 2. Start Sequence (The "Psych Up")
1.  **Pulsing (0-1.5s)**: All nodes pulse **Yellow** 3 times. Visual rhythm for "Standby."
2.  **Ready (1.5s-2.3s)**: All nodes blink **Green** ONCE. Shooter should be at "Low Ready."
3.  **GO (2.3s)**:
    - Timer starts at 1:00.
    - **Initial Spawn**: Exactly ONE random node turns **Bright Red**.
    - *Note*: Previous Min 2 targets removed to prevent spam and focus on acquisition.

## 3. Gameplay Loop (The "Kinetic Flow")
### The "Spam-Proof" Hit Logic (Applies to all Stages)
- **Valid Hit**: Targeted node turns OFF.
- **150ms Global Mask**: System ignores ALL inputs for 150ms immediately after a hit to clear the BB stream.
- **No-Repeat Rule**: The next random spawn cannot be the node that was just hit.

### Stage 0 (0-30s): Warm-up & Acquisition
- **Spawn Delay**: 1.2s (allows reacquiring sight picture).
- **Target Logic**: Single target random spawns.
- **Scoring**:
    - **RT < 750ms**: +10 pts (Elite).
    - **RT 750-1400ms**: +5 pts (Standard).
    - **RT > 1400ms**: +2 pts (Slow).

### Stage 1 (31-50s): Ramp-up
- **Intensity Increases**: Spawn delay drops to 0.8s.
- **Combo Mechanic**: Every 3 successful hits (without a penalty) triggers a **1.5x Multiplier** on subsequent points.

### Stage 2 (51-60s): The "Blitz" Climax
- **Intensity Max**: Spawn delay drops to 0.5s.
- **Final Stand**: In the last 5 seconds, two nodes may activate simultaneously to test peripheral vision and rapid transitions.

### Event: The "Anti-Spam" Penalty
- **Trigger**: Player hits an Inactive (Dark) node.
- **Penalty**: -15 Points.
- **The Freeze**: All nodes flash **ORANGE** for 1.0 second.
- **Logic**: During this second, the 60s timer continues, but no targets spawn. This punishes "spray and pray" behavior by stealing valuable time.

## 4. Game End
1.  **Timer hits 0:00**.
2.  **Cooldown**: All nodes turn **Solid Blue**.
3.  **Dissolve**: After 10s, Blue fades to Black over 3s. nodes will not register any hits in that time and will not react on any hits.
4.  **Results**: Dashboard shows:
    - **Rank**: (e.g., "Sharpshooter" or "Elite Operator").
    - **Total Score**: (Reflecting RT bonuses and penalties).
    - **Precision Rate**: (Successful Hits vs. Inactive Hits).
    - **Spam Penalties**: X (Number of times the "Freeze" was triggered).
    - **Avg Reaction**: (Total RT / Total Hits).

## 5. Leaderboard Update
- The system saves the score to `scores_time_attack_plus.json`.
- Scores are categorized by Difficulty (Distance) and Duration.
- The system highlights the "Precision Rate" on the leaderboard to discourage users from getting high scores via high-volume misses.
