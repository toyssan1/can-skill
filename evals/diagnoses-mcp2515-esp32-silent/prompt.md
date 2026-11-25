---
tags: [canbus]
max_turns: 25
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

ok so i'm trying to read data from my 2019 VW Golf through the OBD port. I have an ESP32 devkit (the 30 pin one) and one of those blue MCP2515 CAN modules from amazon. Wired SPI to the ESP32 (CS on GPIO5, INT on GPIO4), powered the module from the ESP32's 3V3 pin, and CANH/CANL go to pins 6 and 14 of an OBD plug. The little crystal on the module says 8.000.

Sketch prints "init ok" and then nothing at all, ever. Ignition is on. What am I doing wrong?

```cpp
#include <mcp_can.h>
#include <SPI.h>
MCP_CAN CAN0(5);
long unsigned int rxId; unsigned char len; unsigned char buf[8];
void setup() {
  Serial.begin(115200);
  if (CAN0.begin(MCP_ANY, CAN_500KBPS, MCP_16MHZ) == CAN_OK) Serial.println("init ok");
  pinMode(4, INPUT);
}
void loop() {
  if (!digitalRead(4)) {
    CAN0.readMsgBuf(&rxId, &len, buf);
    Serial.println(rxId, HEX);
  }
}
```
