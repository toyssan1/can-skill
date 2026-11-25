# CAN physical layer: wiring, termination, connectors, measurement

Contents
- [Signal levels](#signal-levels)
- [Termination](#termination)
- [Topology and cable](#topology-and-cable)
- [Ground and isolation](#ground-and-isolation)
- [Connector pinouts](#connector-pinouts)
- [Other physical layers](#other-physical-layers)
- [Measuring a bus](#measuring-a-bus)
- [Connecting to a vehicle](#connecting-to-a-vehicle)

## Signal levels

High-speed CAN (ISO 11898-2), measured to ground with a 5 V transceiver:

| State | CANH | CANL | Differential (CANH - CANL) |
|---|---|---|---|
| Recessive (logic 1, idle) | about 2.5 V | about 2.5 V | about 0 V |
| Dominant (logic 0) | about 3.5 V | about 1.5 V | about 2 V |

- Receiver thresholds: differential above 0.9 V is dominant, below 0.5 V is recessive.
- Recessive is not driven: the termination resistors pull the pair together. That is why termination is not optional.
- 3.3 V transceivers (SN65HVD230, TCAN33x) idle near 2.3 V and swing a little less. They interoperate with 5 V transceivers on the same bus because only the differential voltage matters and receivers accept a wide common-mode range (typically -2 to +7 V, more on modern parts).
- A multimeter on an active bus reads averages: CANH about 2.6-2.8 V, CANL about 2.2-2.4 V. Both stuck at 2.5 V means idle or asleep. Either line at 0 V or battery voltage means a short.

## Termination

- **120 ohm between CANH and CANL at each of the two physical ends** of the bus, and nowhere else. This matches the cable impedance and provides the recessive state.
- **Check with power off: 60 ohm between CANH and CANL.** 120 ohm means one terminator is missing. 40 ohm or less means too many. Open circuit means none, or a broken wire.
- Do this measurement first for any "nothing works" problem. It takes ten seconds and resolves a large share of them.
- Cheap modules (MCP2515 boards, SN65HVD230 breakouts, many USB adapters) carry an onboard 120 ohm, often behind a jumper (J1 on the blue MCP2515 board) and sometimes soldered in permanently. Three such modules on one bus give 40 ohm. Remove the extras.
- A bench bus of two nodes needs both terminators. A short bench bus at 500k or less often works with one, which hides the mistake until the cable gets longer.
- Tapping an existing vehicle or machine bus: it is already terminated. **Add no termination** on your tap.
- Split termination (two 60 ohm resistors in series with 4.7 nF from the centre to ground) improves EMC and is what most ECUs use. It measures the same 60 ohm across the bus.
- An unterminated bus still shows dominant bits but the recessive edge decays slowly, so bits smear at higher bitrates. On a scope this looks like shark fins.

## Topology and cable

- A line (daisy chain) with short stubs. Not a star, not a ring. Star topologies cause reflections; at CAN FD data rates they need SIC transceivers or careful design.
- Stub length: keep under 0.3 m at 1 Mbit/s. At 500k about 1 m is safe, at 250k and below a few metres. For CAN FD at 2 Mbit/s and more keep stubs under about 10-30 cm.
- Cable: twisted pair, 120 ohm characteristic impedance. Shielding helps in noisy environments, with the shield grounded at one point. For bench work at 500k over a metre or two, almost any twisted pair works, and untwisted jumper wires work over tens of centimetres.
- Total length against bitrate: 1 Mbit/s 25-40 m, 500k 100 m, 250k 250 m, 125k 500 m, 50k 1 km.
- Node count: 32 by the original standard; modern transceivers support 100 or more.

## Ground and isolation

- CAN is differential but not floating. Nodes need a common reference within the transceiver's common-mode range. Between separately powered devices, connect ground as well as CANH and CANL. A USB adapter on a laptop and a vehicle normally share ground through the OBD connector pins 4/5.
- Missing ground often still "works" until a ground offset or noise exceeds the common-mode range, then fails intermittently.
- Use an isolated transceiver or isolated USB adapter across different power domains: high-voltage EV systems, industrial equipment, long cable runs, or a mains-powered PC connected to a vehicle on a charger. This also protects the laptop.

## Connector pinouts

**OBD-II / SAE J1962 (16-pin, under the dash)**

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | manufacturer discretion (GM single-wire CAN) | 9 | manufacturer discretion |
| 2 | SAE J1850 bus + | 10 | SAE J1850 bus - (PWM only) |
| 3 | manufacturer discretion (Ford MS-CAN high) | 11 | manufacturer discretion (Ford MS-CAN low) |
| 4 | chassis ground | 12 | manufacturer discretion |
| 5 | signal ground | 13 | manufacturer discretion |
| **6** | **CAN high (ISO 15765-4)** | **14** | **CAN low (ISO 15765-4)** |
| 7 | K-line (ISO 9141-2 / ISO 14230-4) | 15 | L-line (optional) |
| 8 | manufacturer discretion | **16** | **battery positive, unswitched** |

Pin 16 is always live and typically fused at 10-15 A or less: fuse anything you power from it and mind the standby current, a permanently plugged-in device can drain the battery. Pins 1, 3, 8, 9, 11, 12, 13 vary by manufacturer and often carry additional CAN buses.

**DB9 / D-sub 9 (CiA 303-1, used by PEAK, Kvaser, Vector, most adapters)**

| Pin | Signal |
|---|---|
| 2 | CAN low |
| 3 | CAN ground |
| 7 | CAN high |
| 9 | optional supply (V+) |
| 5 | optional shield |
| 6 | optional ground |

**OBD-II to DB9 cables come in two incompatible wirings.** The CiA-style cable puts CAN high on DB9 pin 7 and CAN low on pin 2. The other common style (used by SparkFun and some shields) puts CAN high on DB9 pin 3 and CAN low on pin 5, with ground on pin 2. A mismatched cable shorts CAN low to ground or simply shows nothing. Check with a continuity tester before first use.

**M12 5-pin A-coded (CANopen, DeviceNet, NMEA 2000 Micro-C)**: 1 shield/drain, 2 V+, 3 ground, 4 CAN high, 5 CAN low. (DeviceNet/NMEA 2000 colours: white = CAN high, blue = CAN low, red = V+, black = ground.)

**J1939 9-pin Deutsch (heavy vehicles)**: A ground, B battery +, C CAN high, D CAN low, E shield, F and G second bus or J1708, H and J OEM. The black "type 1" connector is 250 kbit/s; the green "type 2" connector signals a 500 kbit/s capable vehicle and physically rejects type 1 plugs.

Wire colours vary by manufacturer and are not a standard. Twisted pairs are the reliable sign of a CAN bus in a harness. Verify with a meter (2.5 V idle on both wires, 60 ohm between them with power off).

## Other physical layers

| Layer | Speed | Notes |
|---|---|---|
| Low-speed fault-tolerant CAN (ISO 11898-3) | up to 125 kbit/s | Keeps working with one wire broken or shorted. Different levels (CANH idles near 0 V, CANL near 5 V) and per-node termination. **Not compatible with a high-speed transceiver**; needs a TJA1055-class part. Found on older body and comfort buses (Fiat, PSA, older Mercedes/BMW/VW) |
| Single-wire CAN (SAE J2411) | 33.3 kbit/s (83.3 in high-speed mode) | GMLAN low-speed on OBD pin 1. One wire plus ground, up to about 4 V swing. Needs a single-wire transceiver (TH8056, NCV7356) |
| CAN FD SIC (CiA 601-4) | 5-8 Mbit/s | Transceivers that actively damp ringing, for star-like topologies |
| LIN | 19.2 kbit/s | Not CAN: a single-wire UART-based sub-bus. A CAN adapter cannot read it |

## Measuring a bus

Multimeter, in this order:
1. Power off: CANH to CANL resistance (60 ohm).
2. Power off: CANH to ground and CANL to ground (should be kilo-ohms or more; a low reading is a short or a damaged transceiver).
3. Power on: CANH about 2.5-2.8 V, CANL about 2.2-2.5 V to ground.

Oscilloscope:
- Probe CANH and CANL to ground on two channels, or use math (CH1 - CH2) for the differential signal. Trigger on the falling edge of CANL.
- Healthy: clean rectangular bits, 2 V differential, flat recessive level, mirror-image CANH and CANL.
- Narrowest pulse width is one bit time (2 us at 500k).
- Slow rising recessive edge: missing termination or too much capacitance. Ringing after edges: stubs or wrong termination. Unequal amplitude between frames: different nodes transmitting, which is normal and useful for telling who sent what. A taller pulse in the ACK slot is normal (several nodes drive it at once). CANH and CANL moving together: a ground offset problem.
- A 6-bit dominant burst that cuts a frame short is an error flag.

Logic analyser: connect to the transceiver's RXD pin, or to CANL with a threshold near 2 V. Sample at 10x the bitrate or more. Sigrok/PulseView and Saleae both decode CAN and can report the bitrate.

## Connecting to a vehicle

- Start with the OBD-II port pins 6 and 14, ground on 4/5.
- **Most vehicles built since roughly 2010-2018 (the year varies by manufacturer) put a gateway between the OBD port and the internal buses.** Through the port you then see nothing until you send diagnostic requests, and never the normal broadcast traffic. To capture broadcast traffic, tap an internal bus behind the gateway: at a module connector, at the gateway itself, or at the connector behind the radio or instrument cluster. Use a T-harness or breakout so the factory wiring stays intact. Avoid insulation-piercing probes on safety-relevant harnesses.
- Vehicles have several buses at different speeds: powertrain, chassis, body/comfort, infotainment, ADAS. The signal you want may not be on the bus you tapped.
- Buses sleep with ignition off. Some wake on door open, some only with ignition on.
- Keep your tap stub short, add no termination, and start in listen-only mode.
