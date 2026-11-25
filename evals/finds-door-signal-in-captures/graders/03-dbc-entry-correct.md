---
type: llm
focus: trace
weight: 1
---

The response or a file it wrote contains a DBC message definition for the door signal it recommends: either a `BO_ 947` line with length 4 followed by an `SG_` line at position `10|1`, or a `BO_ 1192` line with length 6 followed by an `SG_` line at position `7|1`. The SG_ line is complete: name, position, byte order and sign, factor and offset, range, unit and receiver.
