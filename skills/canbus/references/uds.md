# ISO-TP transport and UDS diagnostics

ISO-TP (ISO 15765-2) carries messages longer than one CAN frame. UDS (ISO 14229) is the manufacturer diagnostic protocol on top of it: reading data by identifier, trouble codes for every ECU, actuator tests, coding and flashing. OBD-II uses the same transport with its own small service set (`obd2.md`).

Contents
- [ISO-TP frames](#iso-tp-frames)
- [Flow control and timing](#flow-control-and-timing)
- [Addressing](#addressing)
- [ISO-TP pitfalls](#iso-tp-pitfalls)
- [ISO-TP tooling](#iso-tp-tooling)
- [UDS message format](#uds-message-format)
- [Services](#services)
- [Negative response codes](#negative-response-codes)
- [Sessions, timing, tester present](#sessions-timing-tester-present)
- [Security access](#security-access)
- [Reading data and DTCs](#reading-data-and-dtcs)
- [Finding ECUs and identifiers](#finding-ecus-and-identifiers)
- [Services that change the vehicle](#services-that-change-the-vehicle)
- [KWP2000 and other older protocols](#kwp2000-and-other-older-protocols)
- [UDS with python](#uds-with-python)

To read a capture of diagnostic traffic, run `scripts/isotp_decode.py capture.log`: it reassembles and labels every message.

## ISO-TP frames

The first byte's high nibble is the frame type (PCI):

| Type | Byte 0 | Following | Meaning |
|---|---|---|---|
| Single frame | `0L` | L data bytes (1-7) | whole message in one frame |
| First frame | `1L` `LL` | 6 data bytes | starts a message of 0xLLL bytes (8-4095) |
| Consecutive frame | `2N` | 7 data bytes | N = sequence number, starts at 1, wraps F to 0 |
| Flow control | `3S` `BS` `ST` | | sent by the receiver after a first frame |

CAN FD extensions: a single frame longer than 7 bytes uses `00 LL` (length in byte 1, up to 62). A message longer than 4095 bytes uses `10 00` followed by a 32-bit length. Consecutive frames carry up to 63 bytes.

## Flow control and timing

Flow control fields:
- S (flow status): 0 continue to send, 1 wait, 2 overflow (abort).
- BS (block size): number of consecutive frames before the sender must wait for another flow control. 0 = send everything.
- ST (STmin): minimum gap between consecutive frames. `00`-`7F` = 0-127 ms, `F1`-`F9` = 100-900 microseconds, other values reserved.

`30 00 00` means "send it all, as fast as you like" and is what testers normally send.

Sequence for a 20-byte response:
```
7E0  03 22 F1 90 ...              tester -> ECU   single frame request
7E8  10 14 62 F1 90 57 30 4C      ECU -> tester   first frame, 0x014 = 20 bytes
7E0  30 00 00 ...                 tester -> ECU   flow control
7E8  21 30 30 30 30 34 33 4D      consecutive 1
7E8  22 42 35 34 31 33 32 36      consecutive 2   (padding fills the last frame)
```

Timeouts: the sender waits up to 1000 ms for flow control (N_Bs); the receiver waits up to 1000 ms for each consecutive frame (N_Cr). OBD (ISO 15765-4) tightens these.

## Addressing

| Mode | How | Seen on |
|---|---|---|
| Normal | CAN ID alone identifies source and target; one ID per direction | most 11-bit systems: `7E0`/`7E8`, and OEM ranges in `0x700`-`0x7FF` |
| Normal fixed | 29-bit ID `18DA TT SS` (physical) or `18DB TT SS` (functional), TT = target, SS = source | 29-bit OBD (`18DB33F1`, `18DAF110`), many trucks and newer platforms |
| Extended | first data byte is the target address; PCI moves to byte 1, one byte less payload per frame | BMW (`6F1` from the tester, `6xx` back), some others |
| Mixed | like extended, the first byte is an address extension | gateways and remote networks |

Physical addressing targets one ECU and allows multi-frame. Functional addressing (`7DF`, `18DB33F1`) targets all ECUs and is limited to single-frame requests.

Tester address is `F1` by convention. The ECU's response ID is often request ID + 8 (11-bit OBD range) but OEM schemes vary; the reliable way to learn an ECU's ID pair is to scan or to sniff a tool.

## ISO-TP pitfalls

- **No flow control sent**: the ECU sends the first frame and stops. The usual cause of "I only get the first 6 bytes of the VIN".
- Flow control sent on the wrong ID: it must go to the ECU's physical request ID, even when the request went out functionally on `7DF`.
- Unpadded frames: many ECUs ignore frames shorter than 8 bytes. Pad to 8 (`00`, `55`, `AA` or `CC`).
- Ignoring STmin or block size from the ECU's own flow control when you send a long request.
- Treating a `2N` data byte as a PCI, or missing the extended-addressing byte: both shift everything by one.
- Two testers on the bus: each answers the other's first frames with flow control and corrupts both.
- Responses interleaved from several ECUs after a functional request: reassemble per CAN ID.

## ISO-TP tooling

Linux has ISO-TP in the kernel (module `can-isotp`, mainline since 5.10) with can-utils front ends:

```bash
isotprecv -s 7E0 -d 7E8 -l can0                       # terminal 1: print reassembled responses
echo "22 F1 90" | isotpsend -s 7E0 -d 7E8 -p AA can0   # terminal 2: send, padded with AA
isotpdump -s 7E0 -d 7E8 -c -a can0                    # watch both directions with PCI decoded
```

`-s` is the ID this side transmits on, `-d` the ID it listens to. Add `-x <addr>` for extended addressing.

Python: `pip install can-isotp` gives a socket wrapper for the kernel module and a pure-Python stack that runs over any python-can bus (also on macOS and Windows).

## UDS message format

```
request:            SID  [sub-function]  [parameters...]
positive response:  SID + 0x40  [echo of sub-function / identifier]  [data...]
negative response:  7F  SID  NRC
```

Bit 7 of a sub-function byte (`0x80`) asks the ECU to suppress the positive response; `3E 80` is the usual silent tester-present.

## Services

| SID | Name | Typical request | Risk |
|---|---|---|---|
| 10 | DiagnosticSessionControl | `10 01` default, `10 02` programming, `10 03` extended | a state change, not a read: a non-default session can suspend normal functions until it times out; `10 02` is medium |
| 11 | ECUReset | `11 01` hard, `11 02` key off/on, `11 03` soft | medium: restarts the ECU |
| 14 | ClearDiagnosticInformation | `14 FF FF FF` all groups | medium: erases fault memory |
| 19 | ReadDTCInformation | `19 02 <status mask>`, `19 01`, `19 04`, `19 06`, `19 0A` | none |
| 22 | ReadDataByIdentifier | `22 F1 90` (one or more 2-byte DIDs) | none |
| 23 | ReadMemoryByAddress | `23 <format> <address> <size>` | none, usually locked |
| 27 | SecurityAccess | `27 01` request seed, `27 02 <key>` send key | none by itself |
| 28 | CommunicationControl | `28 03 01` disable normal messages | high: silences the ECU on the bus |
| 29 | Authentication | certificate-based access (2020 edition) | none by itself |
| 2A | ReadDataByPeriodicIdentifier | ECU streams data on its own | low |
| 2C | DynamicallyDefineDataIdentifier | build a custom DID from others | low |
| 2E | WriteDataByIdentifier | `2E <DID> <data>` | **high**: coding, VIN, configuration |
| 2F | InputOutputControlByIdentifier | `2F <DID> 03 <state>` short-term adjust, `00` return control | **high**: drives actuators |
| 31 | RoutineControl | `31 01 <RID>` start, `02` stop, `03` results | **high**: erase memory, calibrations, tests |
| 34 / 35 | RequestDownload / RequestUpload | start a transfer to / from the ECU | **high** |
| 36 | TransferData | `36 <block counter> <data>` | **high** |
| 37 | RequestTransferExit | end of transfer | high |
| 38 | RequestFileTransfer | file-based transfer | high |
| 3D | WriteMemoryByAddress | | **high** |
| 3E | TesterPresent | `3E 00` or `3E 80` | none |
| 85 | ControlDTCSetting | `85 02` off, `85 01` on | medium: stops fault logging |
| 86, 87, 84, 83 | ResponseOnEvent, LinkControl, SecuredDataTransmission, AccessTimingParameter | | rare |

To recognise a reflash in a capture (this is what one looks like, not a procedure to follow): `10 03`, `85 02`, `28 03 01` (functional), `10 02`, `27` unlock, `31 01 FF 00` erase, `34`, repeated `36`, `37`, `31 01` checksum/dependency check, `11 01`. Every manufacturer adds its own routines, checks and signatures, and an interrupted or improvised sequence can leave an ECU that does not boot. Flashing is done with the manufacturer's tool or a process already proven on that exact ECU, never assembled from this outline.

## Negative response codes

| NRC | Name | What it tells you |
|---|---|---|
| 10 | generalReject | |
| 11 | serviceNotSupported | this ECU does not implement the service at all |
| 12 | subFunctionNotSupported | service exists, that sub-function does not |
| 13 | incorrectMessageLengthOrInvalidFormat | the ECU implements the service and rejected the length or format of this request. It shows the service exists; it does not show that the identifier does |
| 14 | responseTooLong | ask for fewer DIDs at once |
| 21 | busyRepeatRequest | retry shortly |
| 22 | conditionsNotCorrect | wrong vehicle state: engine running, speed not zero, voltage, wrong order |
| 24 | requestSequenceError | e.g. key sent before a seed was requested |
| 25 | noResponseFromSubnetComponent | a gateway could not reach the target |
| 31 | requestOutOfRange | this DID/RID/address or parameter value is not accepted: absent, or not available in this session or state |
| 33 | securityAccessDenied | **it exists, but needs unlocking**. Distinguishes locked from absent |
| 34 | authenticationRequired | needs service 29 authentication |
| 35 | invalidKey | wrong key; counts toward lockout |
| 36 | exceededNumberOfAttempts | locked out |
| 37 | requiredTimeDelayNotExpired | wait (often 10 s to 10 min, sometimes across power cycles) |
| 70 | uploadDownloadNotAccepted | |
| 71 | transferDataSuspended | |
| 72 | generalProgrammingFailure | flash erase or write failed |
| 73 | wrongBlockSequenceCounter | |
| **78** | **requestCorrectlyReceived-ResponsePending** | **not an error**: the ECU needs more time. Keep waiting for the real answer, up to the P2* the ECU reported in its `10 xx` response (5 s is common, not guaranteed); it may repeat |
| 7E | subFunctionNotSupportedInActiveSession | not available in the current session. Which session allows it is ECU-specific (often extended, `10 03`) |
| 7F | serviceNotSupportedInActiveSession | as 7E, for the whole service |
| 81-93 | rpmTooHigh, rpmTooLow, engineIsRunning, engineIsNotRunning, engineRunTimeTooLow, temperatureTooHigh/Low, vehicleSpeedTooHigh/Low, throttle/pedal too high/low, transmission not in neutral / not in gear, brake switch not closed, shifter not in park, torque converter clutch locked, voltageTooHigh (92), voltageTooLow (93) | precondition not met |

## Sessions, timing, tester present

- Sessions: `01` default (reading only), `02` programming, `03` extended (most actuator tests, writes and many DIDs live here), `40`-`5F` manufacturer-specific. The response to `10 xx` includes the ECU's timing for that session: P2 (commonly 50 ms) and P2* (commonly 5000 ms, sent in 10 ms units). Use the values the ECU reports, not the common ones.
- A non-default session times out after 5 s without a request (S3) and the ECU falls back to default, relocking security. Send `3E 80` every 2 s or so to hold it.
- Wait up to P2 for an answer. After an NRC 78, wait up to P2* and restart that wait on every further 78.
- Session changes and resets reset security access.

## Security access

1. `27 01` (odd sub-function = request seed for that level). Response `67 01 <seed>`.
2. Compute the key from the seed with the ECU's algorithm and a secret.
3. `27 02 <key>` (even = send key). Response `67 02` on success.

An all-zero seed means that level is already unlocked. Wrong keys lead to NRC 35, then 36 and enforced delays (37). The algorithm is manufacturer- and often ECU-specific and is not public; newer vehicles use certificate-based authentication (service 29) with online authorisation. Reading data usually needs no unlock. Unlocking an ECU you do not own or are not authorised to work on is out of scope; so is brute-forcing keys, which also risks permanent lockout.

## Reading data and DTCs

Standard identifiers (ISO 14229-1 range `F180`-`F19F`), where implemented:

| DID | Content | DID | Content |
|---|---|---|---|
| F186 | active diagnostic session | F190 | VIN |
| F187 | manufacturer spare part number | F191 | ECU hardware number |
| F188 | ECU software number | F193 | supplier hardware version |
| F189 | ECU software version | F194 | supplier software number |
| F18A | system supplier | F195 | supplier software version |
| F18B | ECU manufacturing date | F197 | system name / engine type |
| F18C | ECU serial number | F19E | ODX file identifier |

Everything else (`0000`-`EFFF`, `FD00`-`FEFF`) is manufacturer-defined: the same DID means different things on different ECUs. `F400`-`F4FF` mirror OBD PIDs on OBDonUDS vehicles.

DTCs: `19 02 FF` returns all DTCs matching any status bit: `59 02 <availability mask>` then 4 bytes per DTC, three DTC bytes and one status byte.

| Status bit | Meaning |
|---|---|
| 0 (0x01) | testFailed (failing right now) |
| 1 (0x02) | testFailedThisOperationCycle |
| 2 (0x04) | pendingDTC |
| 3 (0x08) | **confirmedDTC** (stored) |
| 4 (0x10) | testNotCompletedSinceLastClear |
| 5 (0x20) | testFailedSinceLastClear |
| 6 (0x40) | testNotCompletedThisOperationCycle |
| 7 (0x80) | warningIndicatorRequested |

`19 02 08` lists confirmed faults; `19 02 09` adds currently failing ones. `19 04 <DTC> <record>` reads the snapshot (freeze frame) of one DTC, `19 06 <DTC> FF` its extended data (counters, ageing), `19 0A` every DTC the ECU supports. The third DTC byte is the failure type (`11` short to ground, `12` short to battery, `13` open circuit, `1C` voltage out of range, `62` signal compare failure, and so on).

## Finding ECUs and identifiers

Discovery is active: it sends requests to every address, and step 4 changes the diagnostic session. Nothing below writes data, but none of it is passive, and an ECU can react to a request it was never meant to receive. Before starting, confirm with the user that they own or are authorised to test the equipment, which ECU or bus is the target, and that it is in a safe state (parked, ignition on, engine off, stable supply). Prefer a bench ECU when there is one, and capture what a scan tool already does (step 5) before sweeping anything.

1. ECUs: send `02 10 01` (or `02 3E 00`) to each candidate request ID (`0x700`-`0x7FF` for 11-bit; `18DAxxF1` for xx = 00-FF) and note every ID that answers, positively or negatively. Any answer proves an ECU is there.
2. Identity: `22 F1 90`, `22 F1 87`, `22 F1 95` and neighbours.
3. Supported services: send each SID with no parameters. NRC 11 = absent; NRC 13 or 12 = present.
4. Identifiers: sweep `22 xx xx` and keep everything that is not NRC 31. Repeat in session `10 03`, where more is visible. NRC 33 marks protected identifiers.
5. Meaning: the bytes are unlabelled. Correlate against known values (change the thing and re-read), or sniff a scan tool that already shows the value: capture while the tool displays it, run `isotp_decode.py`, and match the tool's displayed number against the response bytes to find scale and offset.

Tools that automate this: Caring Caribou (`cc.py uds discovery`, `cc.py uds services`, `cc.py uds dump_dids`), Scapy's automotive scanners, `udsoncan`. See `tools.md`.

Rate-limit sweeps (20-50 ms between requests) and stop if the vehicle shows warnings.

## Services that change the vehicle

`19`, `22` and `3E` in the default session, and `10 01`, do not change the ECU. `10 03` does: it is a session change, small and self-reverting, but a change. Before sending that or anything below, be explicit with the user about what it does:

- `11` reset: the ECU restarts; on a running engine this stalls it.
- `14` clear: erases fault memory and, on engine ECUs, emissions readiness.
- `28`, `85`: silence an ECU or stop fault logging; other ECUs log communication faults.
- `2E` write: changes coding or configuration. Record the original value first.
- `2F`, `31`: move actuators, run pumps, bleed brakes, erase memory. Some routines are irreversible.
- `34`-`37`, `3D`: reprogramming. An interrupted or wrong flash can leave the ECU unrecoverable without bench tools.

Never send these to a moving vehicle. Never fuzz diagnostic services on a vehicle that matters: random `31`/`2E`/`11` requests have destroyed ECUs.

## KWP2000 and other older protocols

- **KWP2000 on CAN (ISO 14230 services over ISO-TP)**: pre-UDS, same framing. Different services: `1A` ReadEcuIdentification, `21` ReadDataByLocalIdentifier (1-byte IDs), `18` ReadDTCByStatus, `17` ReadStatusOfDTC, `14` clear, `30` IO control by local identifier, `3B` WriteDataByLocalIdentifier, `10 8x` sessions, `81`/`82` start/stop communication. Common on roughly 2000-2010 vehicles; this is where "mode 21" extended PIDs come from.
- **VW TP 2.0**: a VW-group transport older than ISO-TP with dynamic channel setup (`0x200` + address). Needs TP 2.0-aware tooling.
- **GMLAN diagnostics**: GM's pre-UDS service set with its own identifiers (`1A` read DID, `AA` read by packet, `AE` device control).
- **DoIP (ISO 13400)**: UDS over Ethernet on newer vehicles (OBD pins 3, 11, 12, 13 with activation on pin 8). Same UDS services, no CAN involved.

## UDS with python

```python
import can, isotp, udsoncan                      # pip install python-can can-isotp udsoncan
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.client import Client

bus = can.Bus(interface="socketcan", channel="can0")
addr = isotp.Address(isotp.AddressingMode.Normal_11bits, txid=0x7E0, rxid=0x7E8)
stack = isotp.NotifierBasedCanStack(bus=bus, notifier=can.Notifier(bus, []), address=addr,
                                    params={"tx_padding": 0xAA})
cfg = dict(udsoncan.configs.default_client_config)
cfg["data_identifiers"] = {0xF190: udsoncan.AsciiCodec(17)}

with Client(PythonIsoTpConnection(stack), config=cfg, request_timeout=2) as client:
    print(client.read_data_by_identifier(0xF190).service_data.values[0xF190])
    client.change_session(3)                     # extended session
    for dtc in client.get_dtc_by_status_mask(0x08).service_data.dtcs:
        print(f"{dtc.id:06X} status {dtc.status.get_byte_as_int():02X}")
```

`udsoncan` handles NRC 78, timing and DID codecs. The API changes between major versions: check the installed version's documentation when a call fails.
