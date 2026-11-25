# CAN tooling: interfaces, SocketCAN, can-utils, python-can, GUIs, log formats

Contents
- [PC interfaces](#pc-interfaces)
- [SocketCAN setup](#socketcan-setup)
- [Reading interface state](#reading-interface-state)
- [can-utils](#can-utils)
- [macOS and Windows](#macos-and-windows)
- [python-can](#python-can)
- [Python packages at a glance](#python-packages-at-a-glance)
- [cantools](#cantools)
- [GUI and analysis tools](#gui-and-analysis-tools)
- [Diagnostic and security tools](#diagnostic-and-security-tools)
- [Log formats and conversion](#log-formats-and-conversion)

Command syntax here is the stable core. For anything unusual, check `--help` of the installed version before presenting a command as exact.

## PC interfaces

| Interface | Driver / access | CAN FD | Notes |
|---|---|---|---|
| CANable (original), candleLight boards, many "USB to CAN" clones | **candleLight** firmware: Linux `gs_usb`, appears as `can0` with no setup. Or **slcan** firmware: a serial port | no | Cheapest good option. Listen-only supported. Confirm which firmware is flashed |
| CANable 2.0 (STM32G431) and clones | ships with slcan firmware (with FD extensions) | yes, via its slcan dialect | Mainline candleLight does not support this MCU; FD over `gs_usb` needs a board and firmware that state it |
| Innomaker USB2CAN and similar | `gs_usb` | model dependent | Isolated versions available |
| PEAK PCAN-USB / PCAN-USB FD | Linux `peak_usb` in-tree; Windows and macOS drivers | FD model | Reliable timestamps, well supported by every tool |
| Kvaser Leaf Light v2, U100 | `kvaser_usb`; CANlib | U100 | Robust, isolated |
| Vector VN16xx, Intrepid ValueCAN / neoVI | vendor drivers, python-can backends | yes | Professional; needed for CANoe/Vehicle Spy |
| CSS Electronics CANedge | standalone logger to SD card (MF4) | yes | Unattended logging |
| comma.ai panda | USB, `python-panda`, SocketCAN bridge | yes on newer models | Starts in a silent safety mode: it will not transmit until a safety mode is selected |
| Macchina M2 / A0, ESP32 boards with GVRET or slcan firmware | serial (GVRET for SavvyCAN, or slcan) | no | Wireless options; limited throughput |
| Raspberry Pi + MCP2515 / MCP2518FD HAT | SocketCAN (`controllers.md`) | MCP2518FD | Good embedded logger |
| Seeed "USB-CAN Analyzer" (CH340-based) | its own serial protocol; python-can `seeedstudio` backend | no | Not SocketCAN, weak tooling |
| Lawicel CANUSB and compatibles | slcan | no | The origin of the slcan ASCII protocol |
| ELM327 / STN (OBDLink) | serial AT commands | no | An OBD request tool, not a sniffer (`obd2.md`). STN chips can monitor with filters |
| Arduino + MCP2515 printing to serial | - | no | Drops frames on a busy bus: 115200 baud carries about 500 frames/s |

Buying criteria: listen-only mode, hardware timestamps, CAN FD if the target uses it, isolation for vehicle and industrial work, and a driver your tools already speak.

## SocketCAN setup

Linux treats CAN interfaces as network devices.

```bash
# native interfaces (gs_usb, peak_usb, kvaser_usb, mcp251x, mcp251xfd)
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000 listen-only on        # safe default for sniffing
sudo ip link set can0 up

sudo ip link set can0 type can bitrate 500000 sample-point 0.8 restart-ms 100     # normal mode, auto bus-off recovery
sudo ip link set can0 type can bitrate 500000 dbitrate 2000000 fd on              # CAN FD
```

Options (set while the interface is down): `bitrate`, `sample-point`, `dbitrate`, `dsample-point`, `fd on`, `listen-only on`, `loopback on`, `one-shot on`, `restart-ms N`, `berr-reporting on`, `triple-sampling on`, `presume-ack on`, `fd-non-iso on`. `sudo ip link set can0 type can restart` recovers from bus-off by hand.

```bash
# virtual bus for development and replay, no hardware needed
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up                 # add "mtu 72" to the link for CAN FD frames

# serial-line adapters (slcan firmware, Lawicel)
sudo slcand -o -c -s6 /dev/ttyACM0 can0   # -s0..-s8 = 10k 20k 50k 100k 125k 250k 500k 800k 1M
sudo ip link set can0 up
```

`write: No buffer space available` when sending: the transmit queue is full because frames are not leaving, almost always no ACK (nothing else on the bus, wrong bitrate, listen-only on the other side). Fix the bus; `sudo ip link set can0 txqueuelen 1000` only helps genuine bursts.

`cangw` (kernel module `can-gw`) routes and rewrites frames between interfaces, e.g. a transparent bridge for man-in-the-middle work: `sudo cangw -A -s can0 -d can1 -e` and the reverse; `cangw -L` lists, `cangw -F` flushes.

## Reading interface state

```bash
ip -details -statistics link show can0
```

- `state ERROR-ACTIVE` healthy; `ERROR-WARNING`, `ERROR-PASSIVE`: errors accumulating; `BUS-OFF`: the controller has shut down; `STOPPED`: interface down.
- `berr-counter tx 0 rx 0`: live TEC and REC.
- `bitrate 500000 sample-point 0.875`, `tq`, `prop-seg`, `phase-seg1`, `phase-seg2`, `sjw`: what the kernel actually configured, plus the controller's limits and clock.
- Statistics: `bus-errors`, `arbit-lost`, `error-warn`, `error-pass`, `bus-off`, `restarts`, and RX/TX `dropped`/`overrun`.

`candump -e can0,0:0,#FFFFFFFF` prints error frames in text form (enable `berr-reporting on` to get bus-error details).

## can-utils

```bash
candump can0                        # live view
candump -ta -x can0                 # absolute timestamps, TX/RX and FD flag columns
candump -l can0                     # log to candump-<date>.log
candump -L can0 > file.log          # log format to stdout
candump can0,7E8:7F8                # filter: (id & mask) == (value & mask) -> 7E8-7EF
candump can0,123:7FF,456:7FF        # several filters
candump can0,18FEEE00:1FFFFFFF      # 29-bit ID
candump any                         # all interfaces (the log then mixes separate networks: give the scripts --bus NAME)

cansend can0 123#DEADBEEF           # 11-bit ID, 4 bytes
cansend can0 18DAF110#0322F190      # 29-bit ID (8 hex digits)
cansend can0 123#R                  # remote frame
cansend can0 123##1AABBCCDD         # CAN FD: '##' then a flags nibble (1 = BRS) then data

cansniffer -c can0                  # one line per ID, changed bytes highlighted
cangen can0 -g 10 -I 123 -L 8 -D r  # test traffic: 10 ms gap, fixed ID, 8 random bytes
canplayer -I file.log               # replay with original timing onto the logged interface names
canplayer vcan0=can0 -I file.log    # replay frames logged on can0 onto vcan0
canplayer -l i -I file.log          # loop forever
canbusload can0@500000 -r -t -b -c  # bus load
log2asc -I file.log can0 > file.asc # candump log to Vector ASC (asc2log for the reverse)
```

`isotpsend`, `isotprecv`, `isotpdump`, `isotpsniffer` (ISO-TP, see `uds.md`); `j1939spy`, `j1939cat`, `testj1939` (J1939); `slcand`, `slcan_attach` (serial adapters); `canfdtest`, `cansequence` (link tests).

## macOS and Windows

- No SocketCAN. Use **python-can** with a backend that talks to the adapter directly: `gs_usb` (candleLight devices via libusb), `slcan` (serial), `pcan` (PEAK; on macOS with the MacCAN PCBUSB library), `kvaser`, `vector`.
- SavvyCAN runs natively on both and speaks GVRET, slcan-style serial devices and vendor drivers.
- Windows: PCAN-View, Kvaser CanKing and BUSMASTER are free viewers.
- WSL2 can use SocketCAN with a USB adapter passed through by `usbipd`, but the default WSL kernel lacks the CAN modules: it needs a custom kernel build. A Linux VM with USB passthrough or a Raspberry Pi is usually less effort.
- The bundled scripts here read candump-format logs and run anywhere Python does.

## python-can

`pip install python-can` (4.x; Python 3.9+; LGPL-3.0).

```python
import can

bus = can.Bus(interface="socketcan", channel="can0")                         # Linux
# bus = can.Bus(interface="slcan", channel="/dev/tty.usbmodem1", bitrate=500000)
# bus = can.Bus(interface="gs_usb", channel=0, bitrate=500000)
# bus = can.Bus(interface="pcan", channel="PCAN_USBBUS1", bitrate=500000)
# bus = can.Bus(interface="virtual", channel="test")

bus.set_filters([{"can_id": 0x7E8, "can_mask": 0x7F8, "extended": False}])

msg = bus.recv(timeout=1.0)           # None on timeout
if msg:
    print(msg.timestamp, hex(msg.arbitration_id), msg.is_extended_id, msg.dlc, msg.data.hex())

bus.send(can.Message(arbitration_id=0x123, data=[1, 2, 3], is_extended_id=False))

task = bus.send_periodic(can.Message(arbitration_id=0x200, data=[0] * 8, is_extended_id=False), 0.02)
task.stop()

# log everything to a file in the background, format chosen by extension
notifier = can.Notifier(bus, [can.Logger("capture.blf"), can.Printer()])
notifier.stop(); bus.shutdown()
```

- `Message` fields: `arbitration_id`, `is_extended_id`, `data`, `dlc`, `timestamp`, `channel`, `is_remote_frame`, `is_error_frame`, `is_fd`, `bitrate_switch`, `error_state_indicator`, `is_rx`.
- **Always pass `is_extended_id` explicitly.** It defaults to true, so `can.Message(arbitration_id=0x123)` sends a 29-bit frame that 11-bit receivers ignore.
- Command-line tools: `python -m can.logger -i socketcan -c can0 -f out.asc`, `python -m can.player -i socketcan -c vcan0 in.log`, `python -m can.viewer -i socketcan -c can0` (terminal sniffer; for DBC decoding use `cantools monitor`), `python -m can.logconvert in.blf out.log` (format chosen by file extension).
- A config file (`~/.canrc` or `can.ini`) or `CAN_INTERFACE`/`CAN_CHANNEL`/`CAN_BITRATE` environment variables set defaults.

## Python packages at a glance

None of these is needed by the bundled scripts, which use only the standard library and work on saved logs. Install them when the task is to talk to a live bus or to script against a database:

```bash
pip install python-can cantools can-isotp udsoncan        # the core four
```

| Package (pip name) | Use | Licence | Usage in these references checked with |
|---|---|---|---|
| `python-can` | send, receive, filter, periodic transmit, log and convert, on every common interface | LGPL-3.0 | 4.6.1 |
| `cantools` | load DBC/KCD/SYM/ARXML, decode and encode, live monitor, C code generation | MIT | 45.2.0 |
| `can-isotp` (imports as `isotp`) | ISO-TP transport over python-can or the Linux kernel socket | MIT | 2.0.7 |
| `udsoncan` | UDS client: sessions, DIDs, DTCs, security access, transfers | MIT | 1.26.1 |
| `canopen` | CANopen master: SDO, PDO, NMT, EDS loading, network scan | MIT | 2.4.1 |
| `can-j1939` (imports as `j1939`) | J1939 address claiming, PGN send/receive, transport protocol | MIT | 2.0.12 (import only) |
| `obd` (python-OBD) | OBD-II through an ELM327-type adapter, not a raw CAN interface | GPL-2.0 | 0.7.3 (API names only: needs an adapter) |
| `canmatrix` | convert between DBC, ARXML, KCD, XLSX and other database formats | BSD | not exercised |
| `asammdf` | read and convert MF4/MDF logs | LGPL-3.0 | not exercised |
| `scapy` | automotive layers: ISO-TP, UDS, OBD, GMLAN packet classes and scanners | GPL-2.0 | not exercised |

"Checked with" means the code shown in these references was run against that version on python-can's `virtual` interface with simulated devices, not on hardware. APIs move between major versions (`udsoncan` and `can-isotp` in particular): when a call fails, read the installed version's documentation before assuming the reference is right. Mind the licences when shipping a product: `python-can` is LGPL, `obd` and `scapy` are GPL.

Everything that needs no hardware can be developed and tested on a virtual bus: `can.Bus(interface="virtual", channel="test")` in two places in one process, or `vcan0` on Linux.

## cantools

`pip install cantools` (MIT). Reads DBC, KCD, SYM, ARXML and CDD.

```bash
candump can0 | cantools decode vehicle.dbc             # live decode of candump output
cantools decode vehicle.dbc < capture.log              # decode a log
cantools monitor -c can0 vehicle.dbc                   # full-screen live signal view
cantools dump vehicle.dbc                              # print the database with bit-layout diagrams
candump -L can0 | cantools plot vehicle.dbc "*Speed*"  # plot matching signals (needs matplotlib)
cantools convert in.dbc out.kcd
cantools generate_c_source vehicle.dbc                 # C pack/unpack code for embedded use
```

```python
import can, cantools
db = cantools.database.load_file("vehicle.dbc")
bus = can.Bus(interface="socketcan", channel="can0")
for msg in bus:
    try:
        print(db.decode_message(msg.arbitration_id, msg.data))      # {'EngineSpeed': 1726.0, ...}
    except KeyError:
        pass                                                        # ID not in the database
frame = db.get_message_by_name("ENGINE_1")
bus.send(can.Message(arbitration_id=frame.frame_id, is_extended_id=frame.is_extended_frame,
                     data=frame.encode({"EngineSpeed": 1500, "ThrottlePos": 10, "CoolantTemp": 90,
                                        "Counter": 0, "Checksum": 0})))   # every signal of the message is required
```

`cantools generate_c_source` is the low-effort way to put a DBC into firmware: it emits dependency-free C structs with pack, unpack, encode and decode functions.

## GUI and analysis tools

| Tool | Platform | Strength |
|---|---|---|
| **SavvyCAN** (MIT) | Linux, macOS, Windows | The open-source reverse-engineering workbench: sniffer with change highlighting, flow view, range-state finder, graphing, DBC editor, frame sender and fuzzer, ISO-TP/UDS decoding, many log formats |
| **Cabana** (comma.ai, part of openpilot tools) | Linux, macOS | DBC editing against recorded drives with synchronised video; built around panda and opendbc |
| Wireshark | all | Captures SocketCAN interfaces; dissectors for ISO-TP, UDS, OBD-II, J1939, CANopen. No DBC signal decoding. Good for protocol traffic, weak for raw signal hunting |
| PlotJuggler | all | Time-series plotting of decoded signals (CAN/DBC plugin) |
| asammdf | all | View, cut and convert MF4/MDF logs, with DBC decoding |
| BUSMASTER | Windows | Open-source analyser and simulator for PEAK, Kvaser, Vector hardware |
| cangaroo, CANdevStudio | Linux, Windows | Lightweight open-source viewers and simulators |
| PCAN-View (free), PCAN-Explorer | Windows | PEAK hardware |
| Kvaser CanKing, Database Editor (free) | Windows | Kvaser hardware; the Database Editor is a free DBC editor |
| Vector CANalyzer / CANoe, CANdb++ | Windows | Industry standard, commercial. CANdb++ (DBC editor) is included with free Vector downloads |
| ICSim | Linux | Instrument-cluster simulator on `vcan` for practising reverse engineering with no hardware |

## Diagnostic and security tools

For authorised testing of your own equipment.

- **Caring Caribou** (`caringcaribou`, GPL-3.0): diagnostic discovery over SocketCAN. `caringcaribou -i can0 uds discovery`, `uds services 0x7E0 0x7E8`, `uds dump_dids 0x7E0 0x7E8`, `listener`, `xcp discovery`. Module names have changed across versions (`cc.py dcm ...` in older ones): run `caringcaribou -h`.
- **Scapy** automotive layers: `ISOTPSocket`, `UDS`, `OBD`, `GMLAN` packet classes and enumerators.
- **udsoncan** + **can-isotp**: scripted UDS (`uds.md`).
- **canmatrix**, **CRC RevEng**: database conversion; CRC parameter search for checksum hunting.
- **ICSim**, **UDSim**: practice targets.

## Log formats and conversion

| Format | Sample | Notes |
|---|---|---|
| candump log (`.log`) | `(1700000000.123456) can0 123#DEADBEEF` | Text. FD: `123##1DEADBEEF`. Read by every open tool and by the bundled scripts |
| candump console | `  can0  123   [4]  DE AD BE EF` | What `candump can0` prints; the bundled scripts accept it too |
| Vector ASC (`.asc`) | `   0.010000 1  123             Rx   d 4 DE AD BE EF` | Text, header with date and `base hex` |
| Vector BLF (`.blf`) | binary | Compact; python-can reads and writes it |
| PEAK TRC (`.trc`) | `     1)      1234.5  Rx         0123  4  DE AD BE EF` | Several versions; header states which |
| SavvyCAN / GVRET CSV | `1234567,00000123,false,Rx,0,4,DE,AD,BE,EF,,,,` | Header `Time Stamp,ID,Extended,Dir,Bus,LEN,D1..D8`; microsecond timestamps |
| ASAM MF4 (`.mf4`) | binary | CANedge and professional loggers; `asammdf` |
| PCAP / PCAPNG | binary | Wireshark; SocketCAN link type |

Convert with python-can (any pair of formats it supports: `.asc`, `.blf`, `.csv`, `.db`, `.log`, `.mf4`, `.trc`):

```python
import can
with can.LogReader("in.blf") as reader, can.Logger("out.log") as writer:
    for msg in reader:
        writer(msg)
```

Also `log2asc`/`asc2log` (can-utils), SavvyCAN (load one format, save another), `asammdf` for MF4. When someone has a log in an unsupported format, convert it to candump `.log` first and then use the bundled analysis scripts.
