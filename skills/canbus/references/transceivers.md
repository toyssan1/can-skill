# CAN transceivers

The transceiver converts the controller's TXD/RXD logic signals to the differential bus. It decides supply voltage, logic-level compatibility, maximum data rate, fault tolerance and low-power behaviour. Figures below are headline values for selection: confirm against the current datasheet, and note that suffixes (`/3`, `V`, `G`, `H`, `FD`) change the answer.

Contents
- [Selection rules](#selection-rules)
- [Reading part-number suffixes](#reading-part-number-suffixes)
- [NXP](#nxp)
- [Texas Instruments](#texas-instruments)
- [Microchip](#microchip)
- [Other vendors and isolated parts](#other-vendors-and-isolated-parts)
- [Mode pins: the usual reason a transceiver is silent](#mode-pins-the-usual-reason-a-transceiver-is-silent)
- [3.3 V logic with 5 V transceivers](#33-v-logic-with-5-v-transceivers)
- [Board-level design](#board-level-design)

## Selection rules

1. **Logic voltage first.** A 3.3 V MCU (ESP32, STM32, RP2040, SAMD) needs either a 3.3 V transceiver (SN65HVD230 family, TCAN33x) or a 5 V transceiver with a separate logic-supply pin, called VIO (TJA1051T/3, TJA1042T/3, TCAN1042V, MCP2562FD). A 5 V transceiver without VIO drives RXD to 5 V.
2. **Data rate.** Classical CAN up to 1 Mbit/s: anything works. CAN FD: the part must be specified for the data rate (2, 5 or 8 Mbit/s), because loop-delay symmetry matters, not just bandwidth. Legacy parts (TJA1050, MCP2551, SN65HVD230) are 1 Mbit/s parts; they often pass 2 Mbit/s on a bench and fail in the field.
3. **Environment.** 12 V vehicles: bus pins rated for at least +/-40 V faults. 24 V trucks: +/-58 V or +/-70 V. The SN65HVD23x family's lower bus-fault rating suits benches and 12 V hobby use, not 24 V systems.
4. **Low power.** Battery-powered or always-connected devices need standby with wake-on-bus (TJA1042, TCAN1042, MCP2562) or full sleep with an INH output to switch regulators off (TJA1043, TCAN1043).
5. **Isolation.** Different ground domains, high-voltage EV, industrial: ISO1042/ISO1044, ADM3053/ADM3055E, or a digital isolator in front of a standard transceiver. Isolation adds loop delay, which reduces maximum bus length and FD headroom.
6. **Topology.** Stars, long stubs or FD at 5-8 Mbit/s: a signal-improvement (SIC) part, TJA1462 or TCAN1462.

Safe defaults: SN65HVD230 for a 3.3 V classical-CAN hobby node; **TJA1051T/3 or TCAN1042V-class for anything touching a vehicle** (3.3 V logic through VIO, 5 V bus side, FD capable, robust bus pins); MCP2562FD or ATA6563 alongside an MCP2518FD.

The 8-pin parts among these share one pinout (1 TXD, 2 GND, 3 VCC, 4 RXD, 5 VIO or Vref or NC, 6 CANL, 7 CANH, 8 mode pin), so a footprint can take several of them, provided pins 5 and 8 are wired for the part fitted: pin 5 must be fed with the logic supply on a VIO variant and may be left open on others, and pin 8 is standby on some parts and silent on others. The 14-pin sleep-capable parts (TJA1043, TCAN1043) are a different footprint.

## Reading part-number suffixes

| Suffix | Meaning |
|---|---|
| NXP `/3` (TJA1051T/3, TJA1042T/3) | pin 5 is VIO, for 3.3 V logic. Without `/3`, pin 5 is NC or Vref and logic is 5 V |
| TI `V` (TCAN1042V, TCAN1051V) | pin 5 is VIO |
| TI `G` (TCAN1042G, TCAN332G) | specified for 5 Mbit/s CAN FD (base parts 2 Mbit/s, or 1 Mbit/s for TCAN33x) |
| TI `H` (TCAN1042H) | +/-70 V bus fault protection instead of +/-58 V |
| Microchip `FD` (MCP2562FD) | CAN FD rated |
| `-Q1`, `/Q100` | automotive qualified |

## NXP

| Part | Supply | 3.3 V logic | Max rate | Pin 8 | Notes |
|---|---|---|---|---|---|
| TJA1050 | 5 V | no (see below) | 1 Mbit/s | S: high = silent | Legacy. On the blue MCP2515 modules. Not for new designs |
| TJA1051 | 5 V | `/3` variant | 5 Mbit/s FD | S: high = silent | The general-purpose default |
| TJA1042 | 5 V | `/3` variant | 5 Mbit/s FD | STB: high = standby | Standby with bus wake-up |
| TJA1043 | 5 V + battery | VIO | 5 Mbit/s FD | EN, STB_N, INH, WAKE, ERR_N (14-pin) | Sleep mode that switches off the ECU supply |
| TJA1044 | 5 V | `GT/3`, `GTK/3` | 5 Mbit/s FD (G variants) | STB | Cost-reduced TJA1042 |
| TJA1057 | 5 V | `GT/3` | 5 Mbit/s FD | S: silent | Cost-reduced TJA1051 |
| TJA1462, TJA1463 | 5 V | VIO | 8 Mbit/s, SIC | STB / sleep | Signal improvement for difficult topologies |
| TJA1145 | battery + 5 V | VIO | FD | SPI configured | Partial networking (selective wake) |
| TJA1055 | 5 V + battery | - | 125 kbit/s | - | **Low-speed fault-tolerant** CAN. Not interoperable with the parts above |

## Texas Instruments

| Part | Supply | 3.3 V logic | Max rate | Pin 8 | Notes |
|---|---|---|---|---|---|
| SN65HVD230 | 3.3 V | native | 1 Mbit/s | Rs: GND = high speed, resistor = slope control, high = standby | The hobby 3.3 V standard. Pin 5 is a Vref output |
| SN65HVD231 | 3.3 V | native | 1 Mbit/s | Rs: high = sleep | Lower-power variant |
| SN65HVD232 | 3.3 V | native | 1 Mbit/s | not connected | No mode control |
| TCAN330, TCAN332, TCAN334, TCAN337 | 3.3 V | native | 1 Mbit/s; `G` versions 5 Mbit/s FD | 332: none; 334: standby; 330: silent + shutdown; 337: silent + fault | The 3.3 V CAN FD family; replaces SN65HVD23x |
| TCAN1042 | 5 V | `V` variants | 2 Mbit/s; `G` 5 Mbit/s | STB: high = standby | Automotive workhorse; `H` = +/-70 V |
| TCAN1051 | 5 V | `V` variants | 2 Mbit/s; `G` 5 Mbit/s | S: high = silent | |
| TCAN1043 | 5 V + battery | VIO | 5 Mbit/s FD (`G`) | sleep, INH, wake (14-pin) | |
| TCAN1044, TCAN1044A, TCAN1057A | 5 V | `V` variants only (TCAN1044V, TCAN1044AV, TCAN1057AV) | TCAN1044: 8 Mbit/s FD. `A` parts: 5 Mbit/s, 8 Mbit/s only in simple networks | STB (1044) / S (1057) | Newer generation. Order by the full suffix; automotive parts end `-Q1` |
| TCAN1462 | 5 V | `V` variant only (TCAN1462V); pin 5 is not connected on the base part | 8 Mbit/s, SIC | STB | Signal improvement |
| ISO1050 | 5 V bus side, 3.3 or 5 V logic | yes | 1 Mbit/s | - | Isolated, classical |
| ISO1042, ISO1044 | 5 V bus side, 1.8-5 V logic | yes | 5 Mbit/s FD | - | Isolated, FD. Bus side needs its own isolated 5 V supply |

## Microchip

| Part | Supply | 3.3 V logic | Max rate | Pin 8 | Notes |
|---|---|---|---|---|---|
| MCP2551 | 5 V | no | 1 Mbit/s | Rs: slope control / standby | Legacy, not for new designs. On older Arduino shields |
| MCP2561 / MCP2562 | 5 V | MCP2562 (VIO) | 1 Mbit/s | STBY: high = standby | MCP2551 successors. MCP2561 has a SPLIT pin instead of VIO |
| MCP2561FD / MCP2562FD | 5 V | MCP2562FD (VIO) | 8 Mbit/s FD | STBY | Usual partner for MCP2517FD/MCP2518FD |
| MCP2542FD / MCP2544FD | 5 V | VIO on 2542 | 8 Mbit/s FD | STBY | Wake-on-bus variants |
| ATA6560 / ATA6561 | 5 V | ATA6561 (VIO) | 5 Mbit/s FD | STBY; the ATA6560 has a silent pin where the ATA6561 has VIO | |
| ATA6563 | 5 V | VIO | 5 Mbit/s FD | standby | Inside the MCP251863 |

## Other vendors and isolated parts

| Part | Notes |
|---|---|
| Infineon TLE6250, TLE7250, TLE9250, TLE9251V | Automotive. TLE6250 is classical; TLE9250/9251 are FD to 5 Mbit/s, `V` = VIO |
| onsemi NCV7342, NCV7351, NCV7357 | Automotive; NCV7351/7357 are FD capable |
| Analog Devices / Maxim MAX3051 (3.3 V), MAX33040E-MAX33042E | 3.3 V and fault-protected FD parts |
| Analog Devices ADM3053 | Isolated with integrated isolated DC/DC ("isoPower"): one 5 V supply feeds both sides. Classical, 1 Mbit/s |
| Analog Devices ADM3055E, ADM3057E | Isolated with integrated DC/DC, CAN FD |
| Chipanalog CA-IS3050 | Isolated, 1 Mbit/s; on M5Stack CAN units |
| SIT1050, SIT65HVD230, VP230, TJA1050 lookalikes | Low-cost pin-compatible parts on inexpensive modules. Usually fine at 500k on a bench; do not assume the original's fault and ESD ratings |
| Single-wire: Melexis TH8056, onsemi NCV7356 | GMLAN / SAE J2411 single-wire CAN |

## Mode pins: the usual reason a transceiver is silent

Pin 8 selects the mode and **the active level puts the part in the non-working state**:

- STB / STBY high = standby (TJA1042, TJA1044, TCAN1042, MCP2562, ATA6561/6563). In standby the transmitter is off and the receiver only detects wake-up patterns, so the MCU sees nothing.
- S high = silent (TJA1050, TJA1051, TJA1057, TCAN1051). Receive works, transmit does not, and the node never ACKs.
- Rs high = standby (SN65HVD230, MCP2551).

Tie pin 8 to ground for normal operation, or drive it from a GPIO that is **actively driven low**. Many of these pins have an internal pull-up, so a floating pin or an uninitialised GPIO leaves the transceiver in standby or silent. Dev boards frequently route this pin to a GPIO (labelled STB, S, RS, SLNT, EN or "CAN_STBY"): check the schematic when a board receives nothing or cannot transmit.

Other things that silence a transceiver:
- **TXD dominant timeout**: if TXD is held low longer than roughly 0.3-4 ms (part dependent), the driver switches off to protect the bus. This also sets a minimum bitrate of about 10-40 kbit/s on parts with the feature.
- VCC missing or sagging (many go passive below about 4.5 V), or VIO not connected on a `/3` or `V` part.
- TXD and RXD swapped. Controller TX goes to transceiver TXD (pin 1), controller RX to RXD (pin 4): it is not a crossover like a UART.
- A damaged output stage after a bus fault: check CANH and CANL to ground resistance with power off, both should be kilo-ohms or more and roughly equal.

Quick isolation test: put the controller in loopback mode (no transceiver involved). If that works, the problem is the transceiver, its mode pin, the wiring or the bus.

## 3.3 V logic with 5 V transceivers

- Parts with VIO: connect VIO to 3.3 V, VCC to 5 V. This is the correct solution.
- 5 V parts without VIO (TJA1050, MCP2551, TJA1051 without `/3`): TXD input thresholds are TTL-like (about 2 V), so a 3.3 V output drives TXD reliably. **RXD swings to 5 V.** Into a non-5 V-tolerant input (ESP32, RP2040, most SAMD) add a divider (for example 1 k series, 2 k to ground) or a level shifter. STM32 pins marked FT are 5 V tolerant.
- Running a 5 V-only transceiver from 3.3 V does not work reliably, whatever a forum post reports.

## Board-level design

- Decoupling: 100 nF at each supply pin (VCC and VIO) close to the part, plus bulk capacitance on the 5 V rail.
- Termination: fit 120 ohm only if this node is a bus end, ideally behind a jumper or solder bridge. Split termination (2 x 60 ohm, 4.7 nF from the midpoint to ground) for better EMC.
- Protection at the connector: a CAN-specific TVS diode pair (PESD1CAN, PESD2CAN, NUP2105L; low-capacitance "FD" versions for CAN FD). Optional common-mode choke (51-100 uH) for emissions; it can add ringing at FD rates, so many FD designs omit it.
- Route CANH and CANL together as a pair. Keep the stub from connector to transceiver short.
- Vehicle power input: reverse-polarity protection, a TVS rated for load dump, and a regulator with adequate input range (12 V systems see 16 V in normal operation and far higher transients; 24 V systems more). Mind quiescent current for anything left connected to OBD pin 16.
- For automatic power-down, use a transceiver with wake (standby RXD wake-up or INH) and keep only the transceiver powered while asleep.
