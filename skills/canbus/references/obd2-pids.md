# OBD-II service 01 PID table

A, B, C, D are the data bytes after the PID in the response (`41 PID A B C D`). The same PIDs apply to service 02 (freeze frame). A vehicle supports only a subset: read the bitmask PIDs first. `scripts/obd_decode.py --pids` lists what the bundled decoder handles, and `scripts/obd_decode.py 41 ...` decodes a response.

Contents
- [Supported-PID bitmasks](#supported-pid-bitmasks)
- [PIDs 01-1F](#pids-01-1f)
- [PIDs 21-3F](#pids-21-3f)
- [PIDs 41-5F](#pids-41-5f)
- [PIDs 61 and above](#pids-61-and-above)
- [Bit-encoded PIDs](#bit-encoded-pids)
- [Service 09 InfoTypes](#service-09-infotypes)
- [Derived values](#derived-values)

## Supported-PID bitmasks

PIDs `00`, `20`, `40`, `60`, `80`, `A0`, `C0` each return 4 bytes: 32 bits, one per following PID. The most significant bit of A is PID + 1; the least significant bit of D is PID + 0x20 and tells you whether the next bitmask PID exists.

Example `41 00 BE 1F A8 13`: `BE` = 1011 1110 gives PIDs 01, 03, 04, 05, 06, 07; `1F` gives 0C, 0D, 0E, 0F, 10; `A8` gives 11, 13, 15; `13` gives 1C, 1F, 20. Bit for PID 20 set, so request `01 20` next.

Different ECUs return different masks for the same request. Combine them per ECU, not globally.

## PIDs 01-1F

| PID | Bytes | Description | Formula | Unit / range |
|---|---|---|---|---|
| 01 | 4 | Monitor status since DTCs cleared | bit-encoded, see below | |
| 02 | 2 | DTC that caused the freeze frame | DTC encoding | |
| 03 | 2 | Fuel system status | enumerated, see below | |
| 04 | 1 | Calculated engine load | A x 100 / 255 | % |
| 05 | 1 | Engine coolant temperature | A - 40 | degC, -40 to 215 |
| 06 | 1 | Short-term fuel trim, bank 1 | (A - 128) x 100 / 128 | %, -100 to 99.2 |
| 07 | 1 | Long-term fuel trim, bank 1 | (A - 128) x 100 / 128 | % |
| 08 | 1 | Short-term fuel trim, bank 2 | (A - 128) x 100 / 128 | % |
| 09 | 1 | Long-term fuel trim, bank 2 | (A - 128) x 100 / 128 | % |
| 0A | 1 | Fuel pressure (gauge) | A x 3 | kPa, 0 to 765 |
| 0B | 1 | Intake manifold absolute pressure | A | kPa, 0 to 255 |
| 0C | 2 | Engine speed | (256 A + B) / 4 | rpm, 0 to 16383.75 |
| 0D | 1 | Vehicle speed | A | km/h, 0 to 255 |
| 0E | 1 | Timing advance | A / 2 - 64 | deg before TDC |
| 0F | 1 | Intake air temperature | A - 40 | degC |
| 10 | 2 | Mass air flow | (256 A + B) / 100 | g/s, 0 to 655.35 |
| 11 | 1 | Throttle position | A x 100 / 255 | % |
| 12 | 1 | Commanded secondary air status | bit-encoded | |
| 13 | 1 | Oxygen sensors present (2 banks) | bits 0-3 bank 1 sensors 1-4, bits 4-7 bank 2 | |
| 14-1B | 2 | Oxygen sensor 1-8: voltage, short-term trim | A / 200 V; (B - 128) x 100 / 128 % (B = FF: not used for trim) | V 0 to 1.275 |
| 1C | 1 | OBD standard the vehicle conforms to | enumerated, see below | |
| 1D | 1 | Oxygen sensors present (4 banks) | bit-encoded | |
| 1E | 1 | Auxiliary input status | bit 0 = power take-off active | |
| 1F | 2 | Run time since engine start | 256 A + B | s |

## PIDs 21-3F

| PID | Bytes | Description | Formula | Unit |
|---|---|---|---|---|
| 21 | 2 | Distance travelled with MIL on | 256 A + B | km |
| 22 | 2 | Fuel rail pressure relative to manifold vacuum | (256 A + B) x 0.079 | kPa |
| 23 | 2 | Fuel rail gauge pressure (diesel, direct injection) | (256 A + B) x 10 | kPa |
| 24-2B | 4 | Oxygen sensor 1-8, wide range: lambda, voltage | (256 A + B) x 2 / 65536; (256 C + D) x 8 / 65536 | ratio; V |
| 2C | 1 | Commanded EGR | A x 100 / 255 | % |
| 2D | 1 | EGR error | (A - 128) x 100 / 128 | % |
| 2E | 1 | Commanded evaporative purge | A x 100 / 255 | % |
| 2F | 1 | Fuel tank level | A x 100 / 255 | % |
| 30 | 1 | Warm-ups since codes cleared | A | count |
| 31 | 2 | Distance since codes cleared | 256 A + B | km |
| 32 | 2 | Evaporative system vapour pressure | signed(256 A + B) / 4 | Pa |
| 33 | 1 | Barometric pressure | A | kPa |
| 34-3B | 4 | Oxygen sensor 1-8, wide range: lambda, current | (256 A + B) x 2 / 65536; (256 C + D) / 256 - 128 | ratio; mA |
| 3C | 2 | Catalyst temperature, bank 1 sensor 1 | (256 A + B) / 10 - 40 | degC |
| 3D | 2 | Catalyst temperature, bank 2 sensor 1 | same | degC |
| 3E | 2 | Catalyst temperature, bank 1 sensor 2 | same | degC |
| 3F | 2 | Catalyst temperature, bank 2 sensor 2 | same | degC |

## PIDs 41-5F

| PID | Bytes | Description | Formula | Unit |
|---|---|---|---|---|
| 41 | 4 | Monitor status this drive cycle | PID 01's layout with byte A zero. Each monitor's flag bit means *enabled for this drive cycle* (in PID 01 it means *supported*), and its not-complete bit is reported next to it: report the two separately | |
| 42 | 2 | Control module voltage | (256 A + B) / 1000 | V |
| 43 | 2 | Absolute load value | (256 A + B) x 100 / 255 | % |
| 44 | 2 | Commanded air-fuel equivalence ratio | (256 A + B) x 2 / 65536 | lambda |
| 45 | 1 | Relative throttle position | A x 100 / 255 | % |
| 46 | 1 | Ambient air temperature | A - 40 | degC |
| 47, 48 | 1 | Absolute throttle position B, C | A x 100 / 255 | % |
| 49, 4A, 4B | 1 | Accelerator pedal position D, E, F | A x 100 / 255 | % |
| 4C | 1 | Commanded throttle actuator | A x 100 / 255 | % |
| 4D | 2 | Time run with MIL on | 256 A + B | min |
| 4E | 2 | Time since codes cleared | 256 A + B | min |
| 4F | 4 | Maximum values: lambda, O2 voltage, O2 current, MAP | A; B; C; D x 10 | ratio; V; mA; kPa |
| 50 | 4 | Maximum air flow rate | A x 10 | g/s |
| 51 | 1 | Fuel type | enumerated, see below | |
| 52 | 1 | Ethanol fuel percentage | A x 100 / 255 | % |
| 53 | 2 | Absolute evaporative vapour pressure | (256 A + B) / 200 | kPa |
| 54 | 2 | Evaporative vapour pressure | signed(256 A + B) | Pa |
| 55, 56 | 1 or 2 | Short-term, long-term secondary O2 trim, banks 1 and 3 | (A - 128) x 100 / 128; (B - 128) x 100 / 128. B (the second bank) can be absent on a vehicle without that bank: take the count from the response length | % |
| 57, 58 | 2 | Short-term, long-term secondary O2 trim, banks 2 and 4 | same | % |
| 59 | 2 | Fuel rail absolute pressure | (256 A + B) x 10 | kPa |
| 5A | 1 | Relative accelerator pedal position | A x 100 / 255 | % |
| 5B | 1 | Hybrid battery pack remaining life | A x 100 / 255 | % |
| 5C | 1 | Engine oil temperature | A - 40 | degC |
| 5D | 2 | Fuel injection timing | (256 A + B) / 128 - 210 | deg |
| 5E | 2 | Engine fuel rate | (256 A + B) / 20 | L/h |
| 5F | 1 | Emission requirements the vehicle is designed for | bit-encoded | |

## PIDs 61 and above

| PID | Bytes | Description | Formula | Unit |
|---|---|---|---|---|
| 61 | 1 | Driver's demand engine torque | A - 125 | % |
| 62 | 1 | Actual engine torque | A - 125 | % |
| 63 | 2 | Engine reference torque | 256 A + B | N.m |
| 64 | 5 | Engine percent torque at idle and four points | each byte - 125 | % |
| 65-9F | varies | Diesel and heavy-duty data: EGR, turbo, exhaust temperatures, DPF, NOx sensors, SCR/reagent, engine run time | multi-field structures, first byte usually a support bitmap | see SAE J1979 |
| A2 | 2 | Cylinder fuel rate | (256 A + B) / 32 | mg/stroke |
| A4 | 4 | Transmission actual gear | | |
| A6 | 4 | Odometer | (A<<24 + B<<16 + C<<8 + D) / 10 | km |

PIDs from 0x65 upward are multi-byte records with a leading bitmap saying which fields are valid; their layouts are in SAE J1979 and the public "OBD-II PIDs" table on Wikipedia. Do not guess a layout: decode against the published structure, or say that the raw bytes need the standard.

Commonly missing: odometer (A6) on vehicles before about 2019, oil temperature (5C), fuel rate (5E), fuel level (2F) on many. Absence is normal, not a fault.

## Bit-encoded PIDs

**PID 01 (and 41)**, bytes A B C D:
- A bit 7: MIL commanded on. A bits 6-0: number of confirmed emissions DTCs.
- B bit 3: 0 = spark ignition, 1 = compression ignition. B bits 0-2: misfire, fuel system, comprehensive components monitors available. B bits 4-6: the same three monitors **not complete** (1 = incomplete).
- C: non-continuous monitors available. D: the same monitors not complete.

| Bit | Spark ignition (B bit 3 = 0) | Compression ignition (B bit 3 = 1) |
|---|---|---|
| 0 | Catalyst | NMHC catalyst |
| 1 | Heated catalyst | NOx/SCR aftertreatment |
| 2 | Evaporative system | reserved |
| 3 | Secondary air system | Boost pressure |
| 4 | A/C refrigerant | reserved |
| 5 | Oxygen sensor | Exhaust gas sensor |
| 6 | Oxygen sensor heater | Particulate filter |
| 7 | EGR / VVT system | EGR / VVT system |

**PID 03 fuel system status** (A = system 1, B = system 2): 1 open loop (not yet warm), 2 closed loop, 4 open loop (load or deceleration fuel cut), 8 open loop (system failure), 16 closed loop with a feedback fault.

**PID 1C OBD standard**: 1 OBD-II (CARB), 2 OBD (EPA), 3 OBD and OBD-II, 4 OBD-I, 5 not OBD compliant, 6 EOBD, 7 EOBD and OBD-II, 8 EOBD and OBD, 9 EOBD, OBD and OBD-II, 10 JOBD, 11 JOBD and OBD-II, 12 JOBD and EOBD, 13 JOBD, EOBD and OBD-II, 17 EMD, 18 EMD+, 19 HD OBD-C, 20 HD OBD, 21 WWH OBD, 23 HD EOBD-I, 24 HD EOBD-I N, 25 HD EOBD-II, 26 HD EOBD-II N, 28 OBDBr-1, 29 OBDBr-2, 30 KOBD, 31 IOBD I, 32 IOBD II, 33 HD EOBD-IV.

**PID 51 fuel type**: 1 gasoline, 2 methanol, 3 ethanol, 4 diesel, 5 LPG, 6 CNG, 7 propane, 8 electric, 9-15 bifuel running gasoline / methanol / ethanol / LPG / CNG / propane / electricity, 16 bifuel electric and combustion, 17 hybrid gasoline, 18 hybrid ethanol, 19 hybrid diesel, 20 hybrid electric, 21 hybrid electric and combustion, 22 hybrid regenerative, 23 bifuel running diesel.

## Service 09 InfoTypes

| InfoType | Content |
|---|---|
| 00 | supported InfoTypes bitmask |
| 02 | VIN: 17 ASCII characters (`49 02 01` then the VIN) |
| 04 | Calibration IDs: 16 ASCII characters each |
| 06 | Calibration verification numbers: 4 bytes each |
| 08 / 0B | In-use performance tracking, spark / compression ignition |
| 0A | ECU name: 20 ASCII characters |

On CAN the byte after the InfoType is the number of data items. Odd InfoTypes 01, 03, 05, 07, 09 (message counts) are only used on legacy protocols.

## Derived values

- Fuel consumption from MAF (petrol, stoichiometric): `L/h = MAF_g_per_s x 3600 / (14.7 x 740)`, about `MAF x 0.331`. Then `L/100 km = L/h x 100 / speed_km_h`. Diesel and lean-burn engines break the fixed ratio: use PID 5E if supported, or scale by commanded lambda (PID 44).
- No MAF sensor: estimate air mass from MAP, IAT, rpm and displacement (speed-density), with an assumed volumetric efficiency of about 0.8-0.85. Label it an estimate.
- Boost pressure = MAP (0B) - barometric pressure (33).
- Power and torque from OBD data are rough estimates: PIDs 62 and 63 give torque as a percentage of a reference, when supported.
- Gear can be inferred from the ratio of rpm to speed once the ratios are known.
