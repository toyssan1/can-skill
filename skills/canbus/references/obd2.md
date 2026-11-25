# OBD-II diagnostics (SAE J1979 / ISO 15031 / ISO 15765-4)

OBD-II is the legally mandated emissions diagnostic interface. It is a small, standard request/response protocol and is the same on every compliant vehicle, which makes it the reliable starting point. Manufacturer diagnostics (UDS, see `uds.md`) go far beyond it.

Contents
- [Scope and history](#scope-and-history)
- [Protocols on the connector](#protocols-on-the-connector)
- [OBD on CAN: addressing and frames](#obd-on-can-addressing-and-frames)
- [Worked examples](#worked-examples)
- [Services (modes)](#services-modes)
- [Trouble codes](#trouble-codes)
- [Readiness monitors and MIL logic](#readiness-monitors-and-mil-logic)
- [Manufacturer-specific data ("extended PIDs")](#manufacturer-specific-data-extended-pids)
- [OBDonUDS (SAE J1979-2)](#obdonuds-sae-j1979-2)
- [ELM327 and compatible adapters](#elm327-and-compatible-adapters)
- [Talking OBD-II directly on CAN](#talking-obd-ii-directly-on-can)
- [Practical gotchas](#practical-gotchas)

PID formulas are in `obd2-pids.md`. To decode bytes, run `scripts/obd_decode.py`.

## Scope and history

- Mandatory in the US from model year 1996, in the EU (as EOBD) from 2001 for petrol and 2004 for diesel. Since model year 2008 every US vehicle uses CAN (ISO 15765-4) for OBD; EU vehicles followed in practice at the same time.
- It covers emissions-relevant data only: engine and transmission parameters, trouble codes, monitor status. ABS, airbag, body, comfort and most EV battery data are not in OBD-II; they need manufacturer diagnostics.
- Heavy-duty vehicles use J1939 (`j1939.md`) or WWH-OBD (ISO 27145) instead.
- **OBDonUDS (SAE J1979-2)** replaces the classic services with UDS services on new vehicle platforms from about model year 2027. See below.
- Battery-electric vehicles have no emissions obligation: many answer few or no standard PIDs.

## Protocols on the connector

Connector pinout is in `physical-layer.md`. Which pins are populated identifies the protocol:

| Protocol | Pins | Used by | ELM327 number |
|---|---|---|---|
| SAE J1850 PWM, 41.6 kbit/s | 2, 10 | Ford to about 2003 | 1 |
| SAE J1850 VPW, 10.4 kbit/s | 2 | GM to about 2006 | 2 |
| ISO 9141-2 (K-line, 5-baud init) | 7 (15) | European and Asian vehicles to about 2004, Chrysler | 3 |
| ISO 14230-4 KWP2000 (K-line) | 7 (15) | same era; 5-baud or fast init | 4, 5 |
| **ISO 15765-4 CAN** 11-bit / 500k | 6, 14 | most vehicles since 2008 | **6** |
| ISO 15765-4 CAN 29-bit / 500k | 6, 14 | Honda, some others | 7 |
| ISO 15765-4 CAN 11-bit / 250k | 6, 14 | rare | 8 |
| ISO 15765-4 CAN 29-bit / 250k | 6, 14 | rare | 9 |

A CAN adapter cannot read the legacy protocols; those need a K-line or J1850 interface (an ELM327 handles all of them).

## OBD on CAN: addressing and frames

| | 11-bit IDs | 29-bit IDs |
|---|---|---|
| Functional request (to all emissions ECUs) | `0x7DF` | `0x18DB33F1` |
| Physical request to ECU n | `0x7E0`-`0x7E7` | `0x18DAxxF1` (xx = ECU address) |
| Response from ECU n | `0x7E8`-`0x7EF` (request ID + 8) | `0x18DAF1xx` |

`0x7E8` is normally the engine ECU and `0x7E9` often the transmission, but only the responses tell you which ECUs a vehicle has. The rest of this file uses the common 11-bit, 500 kbit/s variant in its examples; the 29-bit and 250 kbit/s variants in the table above work the same way with different IDs or bitrate. `0xF1` is the tester address, `0x33` the functional OBD target.

Every frame is 8 bytes long (DLC 8), padded (0x00, 0x55, 0xAA and 0xCC are all seen). Layout of a single-frame message, which is ISO-TP (`uds.md`):

```
byte 0     byte 1          bytes 2..
length     service (mode)  depends on the service, then padding
```

What follows the service byte depends on the service:

| Service | Request | Positive response (service + 0x40) |
|---|---|---|
| 01 | PID (up to 6 PIDs) | PID echoed, then its data, repeated per PID |
| 02 | PID, frame number | PID, frame number, data |
| 03, 07, 0A | nothing | number of DTCs, then 2 bytes per DTC. No PID |
| 04 | nothing | nothing |
| 06 | monitor ID | monitor ID, then test results |
| 09 | InfoType | InfoType, number of items, data |

- The length byte counts the bytes after it, so it tells you how much of the frame is real: `03 41 0D 58` has three. Never decode padding as data.
- Negative response: `7F <service> <code>`, for example `7F 01 12`. Many ECUs simply do not answer an unsupported PID sent to the functional address.
- An ECU must answer within 50 ms (P2). Wait about 100-200 ms after a functional request to collect answers from several ECUs.
- Responses longer than 7 bytes (VIN, several DTCs) are multi-frame: the tester must send a **flow control** frame to the responding ECU's physical request ID, or the ECU stops after the first frame. With 11-bit IDs that is the response ID minus 8 (`7E8` -> `7E0`). With 29-bit IDs swap the last two bytes (`18DAF110` -> `18DA10F1`).

## Worked examples

Engine speed:
```
7DF  02 01 0C 00 00 00 00 00      request: 2 bytes, service 01, PID 0C
7E8  04 41 0C 1A F8 00 00 00      response: 4 bytes, 41 = 01+40, PID 0C, data 1A F8
                                  rpm = (0x1A * 256 + 0xF8) / 4 = 1726
```

Which PIDs does the vehicle support:
```
7DF  02 01 00 00 00 00 00 00
7E8  06 41 00 BE 1F A8 13 00      bitmask BE 1F A8 13: MSB of the first byte = PID 01
```
The last bit (PID 20) says whether to ask `01 20` for the next 32, and so on (`40`, `60`, `80`, `A0`, `C0`).

VIN, a multi-frame response:
```
7DF  02 09 02 00 00 00 00 00      request service 09, InfoType 02
7E8  10 14 49 02 01 31 47 31      first frame: 0x014 = 20 bytes follow; 49 02 01 then "1G1"
7E0  30 00 00 00 00 00 00 00      flow control from the tester: continue, no block limit, no delay
7E8  21 4A 43 35 34 34 34 52      consecutive frame 1
7E8  22 37 32 35 32 33 36 37      consecutive frame 2    -> VIN 1G1JC5444R7252367
```

Decode any of these:
```bash
python3 scripts/obd_decode.py 41 0C 1A F8
python3 scripts/isotp_decode.py capture.log        # reassembles multi-frame and decodes
```

## Services (modes)

| Service | Purpose | Request | Notes |
|---|---|---|---|
| 01 | Current data | `01 PID` (up to 6 PIDs per request on CAN) | Live values |
| 02 | Freeze frame | `02 PID frame#` | Snapshot stored when a DTC set. PID 02 names that DTC |
| 03 | Stored (confirmed) DTCs | `03` | Response `43 count DTC...` |
| 04 | Clear DTCs and stored data | `04` | Response `44`. See consequences below |
| 05 | Oxygen sensor monitoring | | Not used on CAN; replaced by service 06 |
| 06 | On-board monitoring test results | `06 MID` | Per-monitor test values with limits |
| 07 | Pending DTCs | `07` | Faults seen in the current or last drive cycle, not yet confirmed |
| 08 | Control of on-board systems | `08 TID` | Rare (evap leak test) |
| 09 | Vehicle information | `09 InfoType` | 02 VIN, 04 calibration IDs, 06 calibration verification numbers, 08/0B in-use performance tracking, 0A ECU name |
| 0A | Permanent DTCs | `0A` | Cannot be cleared by a tool |

**Service 04 clears more than codes**: confirmed and pending DTCs, freeze frame, service 06 results, the distance/time-since-clear counters, and it resets every readiness monitor to "not complete". The vehicle then fails an emissions inspection until the monitors have run again, which can take days of mixed driving. It does not clear permanent DTCs. It requires ignition on, and most ECUs want the engine off. Warn before sending it.

## Trouble codes

A DTC is two bytes:

```
byte 1 bits 7-6: letter   00 P (powertrain)  01 C (chassis)  10 B (body)  11 U (network)
byte 1 bits 5-4: first digit (0-3)
byte 1 bits 3-0, byte 2: three hex digits
```

`01 33` is P0133. `C1 00` is U0100. `python3 scripts/obd_decode.py --dtc 0133` converts either way.

- First digit: P0xxx and P2xxx are SAE-defined (same meaning on every vehicle); P1xxx is manufacturer-specific; P3xxx is mixed. For B, C and U codes, 0 is SAE-defined and 1-2 manufacturer-specific.
- Third character of a P code names the subsystem: 1-2 fuel and air metering, 3 ignition and misfire, 4 auxiliary emission controls, 5 speed and idle control, 6 computer and outputs, 7-9 transmission, A-C hybrid propulsion.
- On CAN the response to service 03/07/0A is `43 <count> <DTC> <DTC> ...`. Legacy protocols omit the count and pad with `00 00`. The two cannot be told apart from the bytes, so `scripts/obd_decode.py` reads the CAN layout unless given `--legacy`, and reports `MALFORMED` when the count does not fit the bytes that follow.
- UDS reports 3-byte DTCs: the same two bytes plus a failure-type byte (for example `0x11` short to ground, `0x13` open circuit), written P0133-11.
- The SAE code definitions (J2012) are widely published. Manufacturer-specific code meanings must come from the manufacturer's documentation: do not guess the meaning of a P1xxx code.

## Readiness monitors and MIL logic

Service 01 PID 01 reports the MIL state, the DTC count and which monitors exist and have completed. `obd_decode.py` prints them by name.

- Continuous monitors: misfire, fuel system, comprehensive components.
- Non-continuous, spark ignition: catalyst, heated catalyst, evaporative system, secondary air, oxygen sensor, oxygen sensor heater, EGR/VVT.
- Non-continuous, compression ignition: NMHC catalyst, NOx/SCR aftertreatment, boost pressure, exhaust gas sensor, particulate filter, EGR/VVT.

Each non-continuous monitor runs only under its own enabling conditions (cold start, steady cruise, fuel level window and so on), described by the manufacturer's drive cycle.

Fault life cycle:
1. First failing drive cycle: **pending** DTC (service 07).
2. Failure again on the next drive cycle: **confirmed** DTC (service 03), MIL on, freeze frame stored. Severe catalyst-damaging misfire sets the MIL immediately and flashes it.
3. Three consecutive passing drive cycles: MIL off. The code stays stored and ages out after about 40 warm-up cycles without the fault.
4. **Permanent** DTC (service 0A): stored with a confirmed emissions DTC, survives service 04 and battery disconnection, and erases itself only after the monitor has run and passed.

Inspection programmes check that the MIL is off, that no confirmed codes are stored, and that all (or all but one or two) monitors are complete. That is why clearing codes just before an inspection fails it.

## Manufacturer-specific data ("extended PIDs")

Values outside the standard list (transmission temperature, individual wheel speeds, EV cell voltages, DPF soot load) are read with manufacturer diagnostics, usually UDS service 0x22 ReadDataByIdentifier with a 2-byte data identifier, or KWP2000 service 0x21 on older ECUs. App authors call these "mode 22 / mode 21 PIDs".

They differ from standard PIDs in every respect that matters:
- Sent to a specific ECU's physical address (a "header" such as `7E0`, `7E2`, `7E4`), not to `7DF`.
- The identifier, the scaling and even the responding ECU differ by manufacturer, model and year.
- Responses are often long and multi-frame.
- No standard list exists. Sources: community databases, sniffing a capable scan tool (see `reverse-engineering.md`), or manufacturer documentation.

Scan-tool apps (Torque Pro, Car Scanner, OBD Fusion) take custom definitions as: header, mode + identifier (`220101`), and an equation over response bytes, usually named A, B, C... counting from the first data byte.

Public sources worth knowing (check each repository's licence before reusing data): `OBDb` (per-model signal sets, CC-BY-SA), `iternio/ev-obd-pids` (EV data used by A Better Routeplanner), `JejuSoul/OBD-PIDs-for-HKMC-EVs` (Hyundai/Kia EVs), `commaai/opendbc` (broadcast CAN databases rather than diagnostic PIDs).

## OBDonUDS (SAE J1979-2)

New vehicle platforms move OBD onto UDS services. It is required for new US certifications from about model year 2027 (phased in, heavy-duty first) and permitted earlier. Classic J1979 tools get no answers from such vehicles.

| Classic | OBDonUDS |
|---|---|
| Service 01 PID xx | UDS `22 F4 xx` (PID 0C becomes DID 0xF40C; response `62 F4 0C ...`) |
| Service 09 InfoType xx | UDS `22 F8 xx` (VIN is DID 0xF802) |
| Services 03, 07, 0A, 02 | UDS `19` ReadDTCInformation sub-functions, with 3-byte DTCs and richer status and snapshot data |
| Service 04 | UDS `14` ClearDiagnosticInformation with the emissions group `FF FF 33` |
| Service 06 | UDS `22 F6 xx` |

Detection: send `22 F8 10` to the functional address (`7DF`: `03 22 F8 10`). An OBDonUDS vehicle answers `62 F8 10 ...`; a classic one stays silent or answers negatively, in which case fall back to `01 00`. Addressing and ISO-TP are unchanged. Exact sub-function parameters are defined in SAE J1979-2 itself: consult it or a current tool implementation before relying on byte-level details.

Battery-electric vehicles get their own variant (SAE J1979-3, "ZEVonUDS") with battery state-of-health data.

## ELM327 and compatible adapters

The ELM327 is a protocol-converter chip: ASCII commands over serial, Bluetooth, BLE, WiFi or USB in, OBD requests out. It is the cheapest way to read OBD-II and a poor general CAN sniffer.

Basics: commands end with carriage return. `AT...` configures the adapter. Hex digits are an OBD request. The prompt `>` means ready. Default serial speed is 38400 baud (some clones 9600 or 115200). WiFi clones default to `192.168.0.10` port `35000`.

Typical initialisation:
```
ATZ          reset (prints the version, e.g. "ELM327 v1.5")
ATE0         echo off
ATL0         linefeeds off
ATS0         spaces off (optional, faster)
ATH1         show headers (CAN IDs), needed to tell ECUs apart
ATSP0        automatic protocol search (ATSP6 = force CAN 11-bit/500k)
0100         first request; triggers the search ("SEARCHING...")
ATDPN        report the protocol number found
```

| Command | Effect |
|---|---|
| `ATSH 7E0` | set the request header (CAN ID) for physical addressing or manufacturer requests |
| `ATCRA 7E8` | receive only this ID; `ATCRA` alone resets. `ATCF`/`ATCM` set filter and mask |
| `ATFCSH 7E0`, `ATFCSD 300000`, `ATFCSM 1` | custom flow control for non-standard IDs |
| `ATCAF0` | CAN auto-formatting off: you supply the length byte and see raw frames |
| `ATST hh` | response timeout in 4 ms units; `ATAT1`/`ATAT2` adaptive timing |
| `ATAL` | allow long messages |
| `ATMA` | monitor all traffic until a character is sent. Overflows quickly on a busy bus |
| `ATRV` | battery voltage at the connector |
| `ATDP`, `ATDPN` | describe the current protocol |
| `ATD`, `ATWS`, `ATPC` | defaults, warm start, close protocol |
| `ATCEA hh` | CAN extended addressing byte (BMW and others) |
| `ATCP hh` | upper bits of a 29-bit header |

Appending the expected number of responses speeds polling: `010C1` returns as soon as one ECU has answered.

| Response | Meaning |
|---|---|
| `NO DATA` | no ECU answered in time: unsupported PID, wrong header, ignition off |
| `SEARCHING...` then `UNABLE TO CONNECT` | no protocol found: ignition off, wrong vehicle protocol, bad adapter |
| `CAN ERROR` | no ACK or bus errors: wrong bitrate, not actually connected, bus asleep |
| `BUFFER FULL` | data arrived faster than the serial link could send it |
| `STOPPED` | a character arrived while the adapter was busy: wait for `>` before sending |
| `?` | command not understood (often an unsupported command on a clone) |
| `BUS INIT: ...ERROR`, `FB ERROR`, `DATA ERROR` | legacy protocol initialisation or signal problems |

With headers on, a multi-frame answer arrives as raw frames (`7E8 10 14 49 02 01 31 47 31`...). With headers off it is shown as a byte count and numbered lines (`014`, `0: 49 02 01 ...`).

Clones: nearly every low-cost adapter is a clone, whatever version it reports ("v1.5" was never a genuine release; "v2.1" clones are frequently the least capable). Common defects: missing AT commands (filters, flow control, programmable parameters), only some protocols implemented, unreliable multi-frame handling, slow response. Symptoms are `?` answers to valid commands and failures on extended requests while basic PIDs work. For anything beyond basic PIDs use an adapter with a genuine or STN chip.

STN-based adapters (OBDLink MX+, EX, SX, CX; chips STN1110, STN2120) implement the full ELM327 command set plus `ST` commands, with far larger buffers and higher serial speeds. Useful extras: `STI`/`STDI` identify, `STMA` monitor with filters, `STFAP`/`STFAB` pass and block filters, `STPX` send a message with explicit header and data. They are the practical choice for monitoring and for manufacturer diagnostics.

Throughput: expect 10-25 requests per second on a good adapter over CAN, far fewer on clones and over Bluetooth. Poll fast-changing PIDs often and slow ones (temperatures, fuel level) rarely.

Libraries: `python-OBD` (Python, ELM327 adapters only, GPL-2.0), `ELMduino` (Arduino/ESP32 to an ELM327 over serial or Bluetooth), or talk to the adapter directly, it is just a serial port.

```python
import obd                                   # pip install obd
conn = obd.OBD()                             # auto-detects the port; or obd.OBD("/dev/rfcomm0")
print(conn.protocol_name(), len(conn.supported_commands))
print(conn.query(obd.commands.RPM).value)    # a pint quantity, e.g. 1726.0 revolutions_per_minute
print(conn.query(obd.commands.GET_DTC).value)
```

## Talking OBD-II directly on CAN

With a real CAN interface (SocketCAN adapter, ESP32, MCP2515) you implement the request yourself: send to `0x7DF`, filter for `0x7E8`-`0x7EF`, handle ISO-TP for long answers.

```python
import can                                   # pip install python-can
bus = can.Bus(interface="socketcan", channel="can0")
bus.set_filters([{"can_id": 0x7E8, "can_mask": 0x7F8, "extended": False}])
bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False,
                     data=[0x02, 0x01, 0x0C, 0, 0, 0, 0, 0]))
msg = bus.recv(timeout=0.2)
if msg and msg.data[1] == 0x41 and msg.data[2] == 0x0C:
    print("rpm", (msg.data[3] * 256 + msg.data[4]) / 4)
```

For multi-frame responses use the kernel ISO-TP socket or the `can-isotp` Python package instead of hand-rolling flow control (`uds.md`). On Linux: `isotprecv -s 7E0 -d 7E8 can0` in one terminal and `echo "09 02" | isotpsend -s 7DF -d 7E8 can0` in another.

Embedded pattern (ESP32, STM32, Arduino): transmit one request, wait up to about 100 ms for a frame whose ID is in `0x7E8`-`0x7EF` with `data[1] == service + 0x40` and `data[2] == PID`, decode, move to the next PID. Round-robin a short list instead of flooding. The node must be in normal mode (it has to ACK and transmit), and a diagnostic request is a transmission onto the vehicle bus: keep it to the standard services while driving.

## Practical gotchas

- **Ignition on.** Most ECUs do not answer with ignition off; the gateway may even ignore the request.
- **Silent OBD port is normal** on gateway-equipped vehicles: you see only your own requests and the answers.
- **Secure gateways** (FCA/Stellantis from 2018, and a growing list of others) allow standard emissions requests but block clearing codes, actuator tests and writes without authentication through the manufacturer's service.
- Query what the vehicle supports (`01 00`, `01 20`, ...) before polling, and do not poll unsupported PIDs: each one costs a timeout.
- Do not flood. A request every 20-50 ms is plenty; some ECUs drop requests that arrive before the previous answer.
- Several ECUs can answer one functional request with different values (engine and transmission both report speed). Keep headers on and pick by responder ID.
- Calculated values (fuel economy, power) are estimates derived from MAF or MAP, not measurements.
- Permanently installed devices: watch standby current and bus wake-ups. A device that keeps polling can keep the vehicle's network awake and flatten the battery.
- Some insurance dongles and aftermarket devices on a splitter also send requests; two testers on one port collide.
