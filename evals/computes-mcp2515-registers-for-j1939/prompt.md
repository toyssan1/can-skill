---
tags: [canbus]
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I'm adding a small logger to a tractor's J1939 bus (250 kbit/s). Hardware is an Arduino Nano with an MCP2515 board, the crystal on it is 8 MHz. The stock library timing gave me occasional errors on the long harness, and the J1939 guys told me the sample point should be 87.5%.

What exact CNF1, CNF2 and CNF3 values do I write for 250k at 87.5% with this crystal? And how should I set the thing up so my logger can't upset the tractor?
