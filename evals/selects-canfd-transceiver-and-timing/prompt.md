---
tags: [canbus]
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I'm laying out a small board that plugs into a vehicle's CAN FD network (500 kbit/s arbitration, 2 Mbit/s data, they specify an 80% sample point for both). MCU is an STM32G431 at 3.3 V, FDCAN kernel clock is 40 MHz. The board gets 12 V from the vehicle and I have a 5 V and a 3.3 V rail.

1. Which transceiver should I put on it? I had an SN65HVD230 in my parts drawer.
2. What do I put in the FDCAN init for NominalPrescaler / NominalTimeSeg1 / NominalTimeSeg2 and the Data ones?
3. Anything else I need to get right for 2 Mbit/s?
