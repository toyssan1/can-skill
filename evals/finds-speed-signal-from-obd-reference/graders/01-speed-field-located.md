---
type: llm
focus: trace
weight: 1
---

The response identifies the speed signal in CAN ID 0x1A0 as a 12-bit little-endian field starting at bit 4 (the upper 12 bits of the first two bytes, i.e. DBC 4|12@1+), not as a whole 16-bit read of bytes 0-1.
