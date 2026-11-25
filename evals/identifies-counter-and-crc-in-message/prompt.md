---
tags: [canbus]
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I'm building a bench rig to drive an instrument cluster from a Raspberry Pi with a CAN HAT. capture.log is 30 seconds from the real car at idle. Replaying the capture with canplayer works, the tacho needle sits at idle. But when I send my own 0x0C9 frames with different rpm bytes the cluster ignores them completely.

What is in message 0x0C9 that I'm getting wrong, and what exactly do I need to compute for each frame I send? Python is fine.

Input files: capture.log
