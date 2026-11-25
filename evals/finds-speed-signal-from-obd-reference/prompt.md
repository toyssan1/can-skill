---
tags: [canbus]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I want vehicle speed off the CAN bus for a digital dash I'm building, at a faster rate and finer resolution than OBD gives me. I logged two drives with candump on an internal bus tap while a second adapter polled OBD speed and rpm, so the OBD responses are in the same logs: drive1.log and drive2.log.

Which message and bits carry the speed, and what's the scaling? Give me a DBC line. I don't want to build the dash on a guess, so tell me how sure you are.

Input files: drive1.log, drive2.log
