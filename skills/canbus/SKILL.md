---
name: canbus
description: Expert guidance for CAN bus work - Classical CAN, CAN FD, OBD-II diagnostics, UDS, ISO-TP, J1939, CANopen, NMEA 2000, CAN reverse engineering, and CAN controller and transceiver hardware (MCP2515, MCP2518FD, TCAN4550, ESP32 TWAI, STM32 bxCAN/FDCAN, SN65HVD230, TJA1050/TJA1051, TCAN1042, MCP2562). Use whenever a task involves a CAN or vehicle network - wiring or terminating a bus, bit timing and bitrate problems, bus-off or no-ACK errors, reading OBD-II PIDs or trouble codes, ELM327 adapters, decoding CAN frames or candump logs, finding signals in captures, writing or reading DBC files, SocketCAN, can-utils, python-can, cantools, SavvyCAN, choosing a CAN chip, or writing CAN firmware. Also use when the user is reading or sending data on a vehicle or machine network without saying "CAN bus" - an OBD port or OBD adapter, ECU messages, CAN IDs, a CAN sniffer, a gauge or data logger fed from vehicle data. Not for general car repair, mechanical faults, or wiring that carries no data.
license: MIT
compatibility: Bundled scripts need Python 3.8+ (standard library only). Live-bus commands assume Linux SocketCAN with can-utils; the analysis scripts run on any OS against saved logs.
metadata:
  version: "1.0.0"
---

# CAN bus

Reference knowledge and tools for working on Controller Area Network systems: the protocol itself, the diagnostic and application protocols above it, the chips below it, and the practice of reverse engineering an unknown bus.

Paths below (`references/`, `scripts/`, `assets/`) are relative to the directory containing this file.

## How to work

1. **Establish the setup before advising.** The right answer depends on facts that are cheap to get and expensive to guess: which controller and transceiver (exact part numbers and suffixes), the clock or crystal frequency, supply and logic voltage, the bitrate, the bus being joined (bench, vehicle OBD port, internal vehicle bus, machine), and what is observed (error counters, state, a capture). If they are missing and matter, ask for them in one message. If the task can proceed on a stated assumption, state it and proceed.
2. **Read the matching reference** from the table below before answering in detail. The files hold the exact values (register layouts, pinouts, IDs, formulas) that are easy to misremember. They are long, and each starts with a contents list: for a narrow question read only the section that answers it, and for a plain decode or calculation run the script and skip the reading.
3. **Run the bundled scripts for arithmetic and log analysis** instead of doing it by hand. Bit timing, PID scaling, ISO-TP reassembly and capture statistics are where hand calculation goes wrong.
4. **Work bottom-up when debugging**: wiring and termination, then transceiver, then bitrate and clock, then controller mode and filters, then protocol. Most failures are in the first three layers, whatever the symptom looks like.
5. **Separate standard from proprietary.** OBD-II PIDs, UDS services, J1939 PGNs and CANopen objects are standardised and can be stated with confidence. Broadcast CAN IDs, signal layouts, manufacturer DIDs and "extended PIDs" are specific to a manufacturer, platform and year. Never invent them. Say where they come from (a DBC, opendbc, the manufacturer, or reverse engineering) and how to verify them.
6. **Give exact part numbers, values and commands**, and say which details should be confirmed against a datasheet or the installed tool version.

## Reference files

| Task | Read |
|---|---|
| Frame format, arbitration, error frames, error-passive/bus-off behaviour, CAN FD, CAN XL | `references/can-protocol.md` |
| Bitrate, sample point, register values (CNF1-3, BTR, NBTP), CAN FD data phase, finding an unknown bitrate | `references/bit-timing.md` |
| Wiring, termination, cable, connector pinouts (OBD-II, DB9, M12, Deutsch), scope and meter checks, tapping a vehicle | `references/physical-layer.md` |
| Choosing or programming a controller: MCP2515, MCP2518FD, TCAN4550, ESP32 TWAI, STM32, Teensy, RP2040, Raspberry Pi HATs; boards; firmware libraries; filters | `references/controllers.md` |
| Choosing or wiring a transceiver; 3.3 V vs 5 V; standby/silent pins; protection and layout | `references/transceivers.md` |
| OBD-II: services, addressing, DTCs, readiness, ELM327, OBDonUDS, extended PIDs | `references/obd2.md` |
| OBD-II PID formulas and bit fields | `references/obd2-pids.md` |
| ISO-TP multi-frame transport, UDS services, NRCs, sessions, security access, DIDs, ECU discovery, KWP2000 | `references/uds.md` |
| Trucks, heavy equipment, marine: J1939 PGNs/SPNs, DM1, transport protocol, NMEA 2000, ISOBUS, FMS | `references/j1939.md` |
| CANopen (NMT, SDO, PDO, object dictionary, CiA 402), DeviceNet, DroneCAN, XCP, message counters/checksums/SecOC | `references/canopen.md` |
| Reverse-engineering method: inventory, diffing, signal extraction, scaling, checksums, replay, safety and legal | `references/reverse-engineering.md` |
| Interfaces to buy, SocketCAN, can-utils, python-can, cantools, SavvyCAN, Wireshark, log formats and conversion | `references/tools.md` |
| DBC syntax, bit numbering, Motorola vs Intel, multiplexing, decoding signals in code | `references/dbc.md` |
| Symptom-to-cause tables for a bus that does not work | `references/troubleshooting.md` |

This table is the index. Further down, a bare file name such as `uds.md` means `references/uds.md`, and a bare script name means `scripts/`.

## Scripts

All are standard-library Python, take `--help`, and verify themselves with `--self-test`. Run them rather than re-implementing their logic.

| Script | Use | Example |
|---|---|---|
| `scripts/can_bit_timing.py` | Bit-timing and register values for a controller and clock, classical and CAN FD | `python3 scripts/can_bit_timing.py --profile mcp2515 --clock 8e6 --bitrate 500k --sample-point 80` |
| `scripts/can_log_analyze.py` | Inventory a capture (IDs, periods, constant/varying/counter/checksum bytes); per-bit detail for one ID; diff two captures | `python3 scripts/can_log_analyze.py baseline.log --diff action.log` |
| `scripts/can_signal_search.py` | Find the broadcast signal that tracks a reference (an OBD-II PID in the same capture, a known signal, or a CSV): searches start bit, length, byte order and sign, fits scale and offset, and prints a DBC line as a candidate; `--check` confirms or rejects a candidate on a second capture | `python3 scripts/can_signal_search.py drive.log --obd-pid 0D` |
| `scripts/obd_decode.py` | Decode OBD-II requests and responses: PIDs, supported-PID masks, DTCs, VIN, monitor status | `python3 scripts/obd_decode.py 41 0C 1A F8` |
| `scripts/isotp_decode.py` | Reassemble ISO-TP from a capture and label OBD-II / UDS / KWP2000 messages and negative responses | `python3 scripts/isotp_decode.py capture.log` |

Log input: candump `-l`/`-L` files, candump console output, bare `123#DEADBEEF` lines, or SavvyCAN/GVRET CSV. When a user pastes frames into the conversation, save them to a file (one `ID#DATA` per line is enough) and run the scripts on it; `references/tools.md` shows how to convert other formats. A log recorded from several interfaces holds several separate networks: the scripts stop and ask for `--bus NAME`.

The scripts refuse to guess. `MALFORMED` (a payload shorter than it claims), `BROKEN` or `INCOMPLETE` (a multi-frame message with a gap, or one that never finished) and a non-zero exit status mean the input is short or damaged. Report that and what capture would fix it; do not decode the fragment by hand.

`assets/template.dbc` is a valid DBC to start from when writing one.

## Facts to keep in mind

- A CAN node is a **controller** plus a **transceiver**. A bus needs **120 ohm at each end**: 60 ohm measured across CANH-CANL with power off. Check that first.
- **Lower ID wins arbitration.** IDs are 11-bit or 29-bit; when the two formats share their first 11 bits, the 11-bit frame wins. Classical frames carry up to 8 bytes, CAN FD up to 64.
- A transmitter needs **another node in normal mode to ACK**. Alone, it retransmits forever in error-passive state.
- A node at the **wrong bitrate in normal mode disrupts the whole bus**. Use listen-only mode until the bitrate is confirmed.
- **Classical-only controllers** (MCP2515, ESP32 TWAI on most chips, STM32 bxCAN) cannot coexist with CAN FD traffic except in listen-only mode, and cannot decode it.
- The clock value in code must match the hardware: 8 vs 16 MHz MCP2515 crystals are the classic silent failure.
- 3.3 V microcontrollers need a 3.3 V transceiver or a 5 V transceiver with a VIO pin.
- OBD-II on CAN, in its most common form: 11-bit IDs, request `7DF`, responses `7E8`-`7EF`, 500 kbit/s, connector pins 6 (high) and 14 (low). Some vehicles use 29-bit IDs (`18DB33F1`, `18DAF1xx`) or 250 kbit/s (`obd2.md`). Multi-frame responses need a flow-control frame.
- Modern vehicles put a **gateway** behind the OBD port: it shows diagnostics only, not the internal broadcast traffic.

## Identifying a protocol from a trace

| Observation | Protocol | Next step |
|---|---|---|
| 11-bit IDs `7DF`, `7E0`-`7EF`, or other request/response pairs in `700`-`7FF`; first byte `0x`, `1x`, `2x`, `30` | OBD-II or UDS over ISO-TP | `scripts/isotp_decode.py`; `obd2.md`, `uds.md` |
| 29-bit IDs `18DAxxxx` / `18DBxxxx` | OBD-II or UDS, 29-bit addressing | same |
| 29-bit IDs such as `0CF004xx`, `18FEEExx`, `18FEF1xx`, periodic, 250k or 500k | SAE J1939 | `scripts/can_log_analyze.py --j1939`; `j1939.md` |
| 29-bit IDs `09Fxxxxx`, `0DFxxxxx`, `19Fxxxxx` at 250k on a boat | NMEA 2000 | `j1939.md` |
| 11-bit IDs `700`+n with one data byte (`05`, `7F`), plus `180`-`57F`, `580`+n / `600`+n | CANopen | `canopen.md` |
| 29-bit IDs at 1 Mbit/s on a drone, last byte of each frame changes per transfer | DroneCAN / Cyphal | `canopen.md` |
| 11-bit IDs, each at a fixed period, no request/response | Proprietary broadcast (typical passenger car) | look for a DBC; `reverse-engineering.md` |
| Error frames only, at every bitrate | CAN FD, or a different physical layer (low-speed fault-tolerant, single-wire) | `can-protocol.md`, `physical-layer.md` |

## Common workflows

**Bringing up a new node.** Confirm controller, transceiver, clock and voltages (`controllers.md`, `transceivers.md`). Compute timing with `can_bit_timing.py`. Test in controller loopback first, then on a terminated two-node bench bus, then listen-only on the target bus, then normal mode. Give complete, compilable init code for the user's actual driver and framework, with the clock assumption stated in a comment.

**"It doesn't work."** Go to `troubleshooting.md`. Ask for the termination measurement, part numbers, clock, configured bitrate and error counters if not given. Distinguish "receives nothing" from "cannot transmit": they have different causes.

**Reading vehicle data over OBD-II.** `obd2.md` and `obd2-pids.md`. Query supported PIDs before polling. Use `obd_decode.py` to check any decode. Point out when the data wanted is not in standard OBD-II and needs manufacturer identifiers or a broadcast signal.

**Decoding or reverse engineering a capture.** Run `can_log_analyze.py` for the inventory and identify the protocol with the table above. Then follow `reverse-engineering.md`, choosing the method by the kind of signal: a state the user can switch (door, lights, gear) is found by diffing a baseline against an action capture; a continuous value (speed, rpm, temperature, state of charge) is found with `can_signal_search.py` against a reference recorded in the same capture. What the search prints is a candidate, however good its fit: confirm it on a second capture with `--check` before calling it decoded, then record it in a DBC (`dbc.md`). Present findings as hypotheses with the evidence for each, carry over any caveat the scripts report, and say what capture would settle what is still open. Keep captures on disk and run the scripts on them: never read a whole log into the conversation.

**Diagnostics beyond OBD-II.** `uds.md`. Reading with services 19 and 22 in the default session does not change an ECU, but it is still transmitting on the vehicle's network, so the checks under Safety apply. A session change (`10 03`) is a state change, not a read. State the consequences before giving anyone a request that changes session, resets, clears, writes, runs a routine or reprograms.

**Choosing hardware.** Start from the constraints: logic voltage, classical or FD, vehicle or bench, need for sleep or isolation. Recommend one specific part with the reason and one alternative, not a catalogue.

## Safety and scope

A CAN bus in a vehicle or machine controls physical things, so the cost of a mistake is not a failed test but a stalled engine, a moving actuator or a bricked ECU. Hold to these, and explain them when they apply:

- **Passive capture is the default.** Sniff in listen-only mode on any bus that already works: it cannot disturb the bus. (A single device alone on a bench is the exception: it needs your interface in normal mode to acknowledge its frames.)
- **Before anything is transmitted** onto a vehicle or machine, diagnostic requests included, check three things with the user: that they own it or are authorised to test it, which bus and ECU the traffic is for, and what state it is in (parked or stopped, nobody in the way of anything that could move, stable supply).
- **Never transmit onto a moving vehicle's powertrain, chassis or driver-assistance bus.** Random fuzzing, of IDs or of diagnostic services, belongs only on a bench ECU or a simulator (`ICSim`), never on a complete vehicle. Sending a specific, understood frame (a replayed body command, a simulated module) is for a stationary, supervised vehicle or a bench.
- Before any request that changes state (session change, clear codes, ECU reset, write data, actuator test, routine, flash), say what it does and what cannot be undone. Read and save stored trouble codes before clearing them. Clearing engine codes also resets emissions readiness.
- Work only on equipment the user owns or is authorised to test. Do not help defeat immobilisers, odometers, emissions controls or safety systems, or bypass security access on equipment the user has no right to modify. Reading data, diagnosing faults, building gauges and loggers, retrofits, and authorised security research are all in scope.
- Mind the electrical side: OBD pin 16 is always live and usually has a small fuse; heavy vehicles are 24 V; use isolation across different ground domains.
