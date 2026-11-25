# CANopen and other CAN higher-layer protocols

CANopen (CiA 301) is the dominant protocol in industrial automation, motor drives, medical devices, lifts and robotics. This file also gives short orientation on DeviceNet, DroneCAN/Cyphal, XCP/CCP and vehicle message-security schemes.

Contents
- [Model](#model)
- [COB-ID allocation](#cob-id-allocation)
- [NMT: network management](#nmt-network-management)
- [SDO: reading and writing the object dictionary](#sdo-reading-and-writing-the-object-dictionary)
- [PDO: process data](#pdo-process-data)
- [Object dictionary landmarks](#object-dictionary-landmarks)
- [CiA 402 drives](#cia-402-drives)
- [Working with an unknown CANopen device](#working-with-an-unknown-canopen-device)
- [Tooling](#tooling)
- [Other protocols in brief](#other-protocols-in-brief)

## Model

- Up to 127 nodes, each with a **node ID** (1-127). 11-bit CAN IDs. Bitrates 10k to 1M; 125k, 250k, 500k and 1M are common. Sample point 87.5 %.
- Every device has an **object dictionary (OD)**: a table of parameters addressed by a 16-bit index and an 8-bit sub-index. The device's **EDS** file (electronic data sheet, an INI-style text file) lists it. A DCF is an EDS with configured values.
- **SDO** reads and writes OD entries (confirmed, slow, for configuration). **PDO** broadcasts selected OD entries with no protocol overhead (fast, for real-time data). **NMT** controls node state.
- All multi-byte values are **little-endian**.

## COB-ID allocation

The default "predefined connection set" forms each CAN ID from a 4-bit function code and the 7-bit node ID:

| CAN ID | Object | Direction |
|---|---|---|
| `0x000` | NMT command | master to all |
| `0x080` | SYNC | |
| `0x080` + node | EMCY (emergency) | from node |
| `0x100` | TIME | |
| `0x180` + node | TPDO1 | from node |
| `0x200` + node | RPDO1 | to node |
| `0x280` / `0x300` + node | TPDO2 / RPDO2 | |
| `0x380` / `0x400` + node | TPDO3 / RPDO3 | |
| `0x480` / `0x500` + node | TPDO4 / RPDO4 | |
| `0x580` + node | SDO response | from node |
| `0x600` + node | SDO request | to node |
| `0x700` + node | heartbeat / boot-up | from node |
| `0x7E4` / `0x7E5` | LSS (assign node ID and bitrate) | |

So `0x185` is TPDO1 of node 5, `0x605` an SDO request to node 5 and `0x585` its answer. PDO IDs can be reconfigured, so the table is a default, not a guarantee.

## NMT: network management

Command frame: ID `0x000`, 2 bytes: `<command> <node ID>` (node 0 = all nodes).

| Command | Meaning |
|---|---|
| `01` | start: go to Operational |
| `02` | stop: go to Stopped |
| `80` | go to Pre-operational |
| `81` | reset node (application and communication) |
| `82` | reset communication |

Heartbeat (ID `0x700` + node, 1 byte): `00` boot-up (sent once after reset), `04` stopped, `05` operational, `7F` pre-operational.

**PDOs only flow in Operational.** A device that sends its heartbeat `7F` and no process data is waiting for `000#0100`. SDO works in pre-operational and operational, not in stopped.

## SDO: reading and writing the object dictionary

Requests go to `0x600` + node, answers come from `0x580` + node. Always 8 bytes: command byte, index (2, little-endian), sub-index, 4 data bytes.

Expedited transfer (values up to 4 bytes):

| Command byte | Meaning |
|---|---|
| `40` | read request (upload) |
| `4F` / `4B` / `47` / `43` | read response carrying 1 / 2 / 3 / 4 bytes |
| `2F` / `2B` / `27` / `23` | write request (download) of 1 / 2 / 3 / 4 bytes |
| `60` | write acknowledged |
| `80` | abort; the 4 data bytes are the abort code |

Read the device type (0x1000 sub 0) of node 5:
```
605#40 00 10 00 00 00 00 00
585#43 00 10 00 92 01 02 00        value 0x00020192: profile 402 (0x0192), drive
```
Set the heartbeat interval (0x1017 sub 0) of node 5 to 1000 ms:
```
605#2B 17 10 00 E8 03 00 00
585#60 17 10 00 00 00 00 00
```

Values over 4 bytes use segmented transfer (initiate response `41` with the length, then alternating `60`/`70` segment requests) or block transfer. Let a library do it.

Common abort codes: `0503 0000` toggle bit not alternated, `0504 0000` timeout, `0601 0000` unsupported access, `0601 0001` attempt to read a write-only object, `0601 0002` attempt to write a read-only object, `0602 0000` **object does not exist**, `0604 0041` object cannot be mapped to a PDO, `0607 0010` data type or length mismatch, `0609 0011` **sub-index does not exist**, `0609 0030` value range exceeded, `0800 0000` general error, `0800 0020` data cannot be transferred or stored, `0800 0022` wrong device state. On the wire the code is little-endian: `80 17 10 00 00 00 02 06` is abort `0602 0000`.

## PDO: process data

A PDO is a raw CAN frame of up to 8 bytes whose content is defined by the OD: no index or type information travels with it.

- TPDO n: communication parameters at `0x1800 + n-1`, mapping at `0x1A00 + n-1`. RPDO n: `0x1400 + n-1` and `0x1600 + n-1`.
- Communication parameter sub 1 is the COB-ID (bit 31 set = PDO disabled); sub 2 is the transmission type: 1-240 = send every n-th SYNC, 254/255 = event-driven; sub 3 inhibit time; sub 5 event timer in ms.
- Each mapping entry is a 32-bit value `index (16) | sub-index (8) | length in bits (8)`. `0x60410010` maps object 0x6041 sub 0, 16 bits.

To decode a PDO you sniffed: read its mapping over SDO (`0x1A00` sub 0 gives the count, sub 1.. the entries), or take it from the EDS/DCF. Without either, treat it as an unknown message and reverse engineer it (`reverse-engineering.md`).

To change a mapping: disable the PDO (set bit 31 of the COB-ID), write 0 to mapping sub 0, write the entries, write the count to sub 0, re-enable. Many devices only accept this in pre-operational.

## Object dictionary landmarks

| Index | Content |
|---|---|
| 0x1000 | device type (low 16 bits = device profile number) |
| 0x1001 | error register |
| 0x1003 | predefined error field (error history) |
| 0x1008 / 0x1009 / 0x100A | device name, hardware version, software version (strings) |
| 0x1010 / 0x1011 | store parameters (write the signature "save", bytes `73 61 76 65` on the wire) / restore defaults (signature "load", `6C 6F 61 64`) |
| 0x1014 | EMCY COB-ID |
| 0x1017 | producer heartbeat time in ms (0 = off) |
| 0x1018 | identity: vendor ID, product code, revision, serial number |
| 0x1400-0x15FF, 0x1600-0x17FF | RPDO communication, RPDO mapping |
| 0x1800-0x19FF, 0x1A00-0x1BFF | TPDO communication, TPDO mapping |
| 0x2000-0x5FFF | manufacturer-specific |
| 0x6000-0x9FFF | device-profile objects |

EMCY frame (ID `0x080` + node, 8 bytes): error code (2, little-endian), error register (1), 5 manufacturer bytes. Code `0000` means the error has cleared. Classes: `2xxx` current, `3xxx` voltage, `4xxx` temperature, `5xxx` hardware, `6xxx` software, `7xxx` additional modules, `8xxx` monitoring and communication (`8110` CAN overrun, `8120` error passive, `8130` heartbeat lost, `8140` recovered from bus-off).

Device profiles: 401 generic I/O, 402 drives and motion control, 404 measuring devices, 406 encoders, 418/419 batteries and chargers, 417 lifts, 422 municipal vehicles.

## CiA 402 drives

Servo drives, steppers and inverters follow one state machine driven by the **controlword** (0x6040) and reported by the **statusword** (0x6041).

Enable sequence written to 0x6040: `0x0006` (shutdown: ready to switch on), `0x0007` (switch on), `0x000F` (enable operation). Fault reset: rising edge of bit 7 (`0x0080`). Quick stop: `0x0002`.

Statusword states (mask `0x6F`): `0x00` not ready, `0x40` switch on disabled, `0x21` ready to switch on, `0x23` switched on, `0x27` operation enabled, `0x07` quick stop active, `0x08` fault (bit 3).

Other key objects: 0x6060 mode of operation (1 profile position, 3 profile velocity, 4 profile torque, 6 homing, 8 cyclic sync position, 9 cyclic sync velocity, 10 cyclic sync torque) and 0x6061 its display; 0x607A target position, 0x60FF target velocity, 0x6071 target torque; 0x6064 actual position, 0x606C actual velocity, 0x6077 actual torque; 0x603F last error code.

Enabling a drive makes a motor move. Confirm the mechanical side is safe and limits are set before sending the enable sequence.

## Working with an unknown CANopen device

1. Sniff in listen-only: heartbeats at `0x700` + n reveal node IDs and state; `0x180`-`0x57F` traffic is PDOs.
2. Read identity over SDO: 0x1000, 0x1018, 0x1008.
3. Find the EDS from the manufacturer using vendor ID and product code. It names every object.
4. Read the PDO mappings to label the process data.
5. Node does not answer: wrong bitrate or node ID. LSS (`0x7E5`/`0x7E4`) can query and set both on devices that support it; many have DIP switches or a vendor tool.

## Tooling

- Python: `canopen` (`pip install canopen`): load an EDS, then `node.sdo[0x1018][1].raw`, `node.nmt.state = "OPERATIONAL"`, `node.tpdo.read()`, network scanner included.
- Linux: `cansend can0 000#0100`; `candump can0,700:780` shows all heartbeats; CANopenLinux / CANopenNode provide a full stack and the `cocomm` command tool.
- Embedded stacks: CANopenNode (open source, widely used), Lely CANopen (C++ master/slave), `canopen-stack` (Embedded Office), Zephyr's CANopenNode integration. Commercial stacks from the usual vendors.
- Wireshark dissects CANopen. Vector, PEAK and Kvaser tools load EDS files.
- CANopen FD (CiA 1301) uses CAN FD frames with larger PDOs and a new "USDO" service; rare in the field.

## Other protocols in brief

| Protocol | Recognise it by | Notes |
|---|---|---|
| DeviceNet | 11-bit IDs at 125/250/500k, industrial (Rockwell/Allen-Bradley) | CIP application layer, shared with EtherNet/IP. Master/slave I/O connections; node address (MAC ID 0-63) inside the ID |
| DroneCAN (formerly UAVCAN v0) and Cyphal | 29-bit IDs at 1 Mbit/s on drones and robots; a tail byte ending each frame with start/end/toggle bits and a transfer ID | Open specifications with public data-type definitions. DroneCAN is what ArduPilot and PX4 peripherals use |
| XCP on CAN / CCP | Two fixed IDs with command-response traffic, first byte `0xFF` = connect or positive response | Calibration and measurement protocol for ECU development. Described by A2L files. Gives direct memory read/write, so production ECUs lock or remove it |
| VESC | 29-bit IDs, low byte = controller ID, next byte = command | Open-source motor controllers; packet IDs in the VESC firmware source |
| Tesla, BMS and inverter vendor protocols | fixed 11-bit or 29-bit broadcast IDs, usually 250k or 500k | Many battery and inverter makers publish a CAN matrix (Victron, Pylontech-compatible, SMA). Ask for it before reverse engineering |
| OEM vehicle broadcast traffic | periodic 11-bit IDs at fixed rates, no request/response | Proprietary. Decoded with a DBC (`dbc.md`) or reverse engineered |

**Message protection on modern vehicle buses.** These explain why replayed or injected frames are rejected:
- **Alive counters and checksums** (AUTOSAR E2E profiles): a 4-bit counter and a CRC-8 in each protected message, often with a per-message secret "data ID" mixed into the CRC. Receivers ignore frames with a stale counter or wrong checksum. `can_log_analyze.py` detects the common unsalted forms.
- **SecOC** (AUTOSAR Secure Onboard Communication): a truncated cryptographic MAC plus freshness value appended to the payload, keyed per vehicle. Cannot be forged without the key; reading the data is still possible.
- Gateways and secured diagnostics limit what the OBD port can reach.
