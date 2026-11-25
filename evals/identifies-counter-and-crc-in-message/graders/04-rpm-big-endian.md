---
type: llm
focus: trace
weight: 1
---

The response treats bytes 0-1 of 0x0C9 as the engine-speed bytes the user wants to change, and does not present their width, byte order or scale as proven by this capture: byte 0 never changes in it (the car is idling), so the response either says that a capture with the engine speed varying is needed to confirm them, or states a 16-bit big-endian reading as an assumption.
