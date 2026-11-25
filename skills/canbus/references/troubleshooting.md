# Troubleshooting CAN: symptom to cause

Work from the bottom up: wiring and termination, then transceiver, then bitrate, then controller mode and filters, then protocol. Most "CAN doesn't work" problems are in the first three.

Contents
- [Ten-minute checklist](#ten-minute-checklist)
- [Nothing received](#nothing-received)
- [Cannot transmit](#cannot-transmit)
- [Works, then stops or drops frames](#works-then-stops-or-drops-frames)
- [Vehicle-specific](#vehicle-specific)
- [OBD-II and diagnostics](#obd-ii-and-diagnostics)
- [Platform-specific quick hits](#platform-specific-quick-hits)
- [Isolating the fault](#isolating-the-fault)

## Ten-minute checklist

1. **Power off: 60 ohm between CANH and CANL?** 120 = one terminator missing; 40 or less = too many; open = none.
2. CANH and CANL not swapped, and continuous from end to end. Ground shared between nodes.
3. Power on: both lines near 2.5 V at idle. A line at 0 V or supply voltage is a short.
4. Transceiver powered at its correct voltage, and its mode pin (STB / S / RS / EN) at the level for normal operation. See `transceivers.md`.
5. Controller TX to transceiver TXD, controller RX to transceiver RXD (not crossed).
6. Bitrate identical on every node, and the **clock/crystal value in code equals the hardware** (8 vs 16 MHz MCP2515, PCLK1 on STM32).
7. Controller actually in normal (or listen-only) mode: not configuration, sleep or loopback.
8. Acceptance filters open.
9. At least two nodes in normal mode if anything must be transmitted (someone has to ACK).
10. Read the error counters and state: they say which side of the problem you are on.

## Nothing received

| Clue | Cause | Fix |
|---|---|---|
| Error counters rising, state error-passive or bus-off | wrong bitrate, wrong crystal/clock setting, or CAN FD traffic on a classical controller | correct the bitrate or clock; use an FD-capable interface |
| Counters stay 0, nothing arrives | bus silent (asleep, gateway), RX pin not connected, transceiver in standby, filter rejecting everything | check for activity with a scope or meter; open filters; fix the mode pin |
| STM32 bxCAN, no RX ever | no filter bank configured | configure one accept-all filter before `HAL_CAN_Start` |
| MCP2515 "init OK" but silent | crystal constant wrong, or library left in loopback/config mode | match `MCP_8MHZ`/`MCP_16MHZ`; call `setNormalMode()` / `setMode(MCP_NORMAL)` |
| Receive works only for some IDs | filter or mask misconfigured; standard vs extended mismatch | accept-all first, then narrow |
| Linux: `can0` missing | driver or overlay not loaded, adapter is slcan (serial) not gs_usb | `dmesg`; `slcand` for serial adapters |
| Linux: `can0` up but silent, state ERROR-ACTIVE | listen-only on a bus that is asleep, or wrong pins | generate traffic; check wiring |
| OBD port silent | gateway: normal | send a diagnostic request, or tap behind the gateway |
| Garbage IDs and lengths | bitrate slightly off (resonator, wrong divider) or sample point far off | exact bitrate, crystal clock, 75-87.5 % sample point |

## Cannot transmit

| Clue | Cause | Fix |
|---|---|---|
| Frame repeats forever on a scope, TEC stops at 128, never bus-off | **no ACK**: no other node in normal mode at this bitrate | add a second node; or self-test/loopback mode for single-board tests |
| Linux `write: No buffer space available` | TX queue full because frames are not being ACKed | same as above; not a queue-size problem |
| ESP32 `twai_transmit` returns `ESP_ERR_TIMEOUT` or `TWAI_ALERT_TX_FAILED` | no ACK, bus-off, or driver in listen-only mode | check `twai_get_status_info`; normal mode; recover from bus-off |
| Immediate bus-off | bitrate mismatch, CANH/CANL shorted or swapped, no termination, transmitting an ID another node also sends | scope the bus; fix wiring; pick a unique ID |
| TX pin toggles, bus stays recessive | transceiver in standby or silent mode, unpowered, or TXD-dominant timeout tripped | mode pin low; check VCC |
| The other device never reacts though frames are on the bus | wrong ID format (11 vs 29 bit: python-can defaults to extended), wrong DLC, missing padding, wrong byte order, missing counter/checksum | compare byte-for-byte with a known-good capture |
| CAN FD frames fail, classical frames pass | a classical-only node on the bus is destroying FD frames; TDC not set; ISO vs non-ISO mismatch | remove or silence classical nodes; enable TDC; match ISO mode |

## Works, then stops or drops frames

| Clue | Cause | Fix |
|---|---|---|
| Frames missing at high bus load | receive overflow: polling too slowly, 2-buffer MCP2515, slow serial output | interrupt-driven RX, hardware filters, bigger queues, binary logging instead of printing |
| Printing every frame at 115200 baud | UART is the bottleneck (about 500 frames/s) | raise the baud rate, filter, or buffer |
| ESP32 `TWAI_ALERT_RX_QUEUE_FULL` | application not draining the queue | larger `rx_queue_len`, dedicated RX task |
| Runs for minutes, then bus-off | marginal termination, ground offset, EMI, intermittent connector | scope under real conditions; split termination; shielded pair; common ground |
| Works on the bench, fails in the vehicle | library-default sample point (56-62 %), long stub, added termination, supply noise | 80 % sample point, short stub, remove termination, filter the supply |
| Errors rise with engine running or under load | EMI or supply dips: alternator and ignition noise, shared ground return | twisted pair, proper ground, supply filtering and TVS |
| Dies when a second device is plugged in | that device is at the wrong bitrate in normal mode, or adds a third terminator | listen-only until confirmed; measure 60 ohm |
| Stops after bus-off and never returns | no bus-off recovery implemented | `restart-ms`, `twai_initiate_recovery`, `AutoBusOff`, with back-off |
| Timestamps bunched, periods look wrong | USB or UART batching, not the bus | use hardware timestamps or a better interface |

## Vehicle-specific

- **Warning lights or limp mode after connecting**: the device transmitted (or ACKed at the wrong bitrate), drew the bus down, or its messages conflicted with an ECU's. Disconnect and cycle the ignition. Read and save the stored codes before anything else: they are the record of what happened, and of any fault that was there before. Clear them only once they are saved, the user wants them cleared and the vehicle is theirs to clear (on an engine ECU it also resets emissions readiness). Use listen-only for sniffing.
- **Battery drained overnight**: the device kept the bus awake by transmitting or polling, or has high standby current on OBD pin 16. Stop transmitting when the bus goes quiet and sleep.
- **Device works with ignition on, nothing with ignition off**: buses sleep. Expected.
- **Different IDs than the DBC or forum post**: different model year, platform, trim or market; or you are on a different bus.
- **Value decodes but is slightly wrong**: scale or offset from a different variant; check against OBD-II.
- **Replayed frames are ignored**: rolling counter or checksum, SecOC, or the original sender is still transmitting the real value alongside yours.
- **24 V vehicle**: 12 V-rated electronics and bus-fault ratings are exceeded. Check the supply before connecting.

## OBD-II and diagnostics

| Symptom | Cause |
|---|---|
| No response to `7DF 02 01 00` | ignition off; wrong bitrate (try 250k); 29-bit vehicle (use `18DB33F1`); frame not padded to 8 bytes; node in listen-only; EV with no OBD support |
| Only the first frame of a long response | flow control (`30 00 00`) not sent, or sent to the wrong ID |
| `7F xx 11` or `7F xx 12` | service or PID not supported by that ECU |
| `7F xx 31` | request out of range: identifier absent, or not available in this session or state |
| `7F xx 33` | present but locked: security access or a secure gateway |
| `7F xx 78` repeatedly | not an error: keep waiting for the final response |
| `7F xx 7F` / `7E` | switch to the extended session first |
| ELM327 `NO DATA` | unsupported PID, wrong header, ignition off |
| ELM327 `CAN ERROR` / `UNABLE TO CONNECT` | wrong protocol, no bus, bad clone |
| ELM327 answers `?` to valid AT commands | clone without that command |
| Session drops back after a few seconds | no tester present (`3E 80` every 2 s) |
| Clearing codes or actuator tests refused on a recent vehicle | secure gateway: needs manufacturer authentication |

## Platform-specific quick hits

- **ESP32**: needs an external transceiver; a 5 V-only transceiver's RXD must not drive a GPIO directly; do not mix legacy and new TWAI drivers; classical only (except FD-capable chips); check the board for a transceiver standby GPIO.
- **MCP2515 modules**: 8 MHz crystal vs 16 MHz code; 5 V-only TJA1050 on the blue board; termination jumper J1; SPI chip-select and shared-bus conflicts.
- **STM32**: filter required (bxCAN); PCLK1-based timing; CAN2 depends on CAN1; F103 CAN/USB conflict; pin remap; `HAL_CAN_Start` timeout means the transceiver/RX line is not idle-high.
- **Raspberry Pi**: `oscillator=` must equal the HAT's crystal; interrupt GPIO must match; `dmesg | grep -i mcp`; SPI enabled.
- **Arduino Uno + MCP2515**: 2 kB RAM and slow SPI/serial limit it to light traffic; filter in hardware.
- **USB adapters**: candleLight (`gs_usb`, native `can0`) vs slcan (serial, needs `slcand`); clones may ship either.
- **Teensy 4**: correct bus object (`CAN1`/`CAN2`/`CAN3`) for the pins; CAN3 for FD; external transceiver.

## Isolating the fault

1. **Loopback** (controller internal): proves firmware, bit timing arithmetic and filters with no wiring at all.
2. **Two known-good nodes on a 30 cm terminated bench bus**: proves transceivers and wiring practice. A USB adapter running `candump` plus `cangen` is the ideal second node.
3. **Listen-only on the real bus**: proves bitrate and physical connection without risk.
4. **Normal mode on the real bus**: only after 3 shows clean traffic with zero errors.
5. Scope or logic analyser on TXD, RXD and the bus when the above disagree: is the controller sending, is the transceiver passing it, does the bus look rectangular.

When asking someone for more information, ask for: the controller and transceiver part numbers, the crystal or clock frequency, the measured resistance across CANH/CANL, the configured bitrate and mode, what the error counters or `ip -details -statistics link show can0` report, and the init code.
