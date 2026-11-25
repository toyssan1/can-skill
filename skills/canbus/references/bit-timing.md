# CAN bit timing

Contents
- [The model](#the-model)
- [Choosing values](#choosing-values)
- [Use the calculator](#use-the-calculator)
- [Reference values for common controllers](#reference-values-for-common-controllers)
- [CAN FD data phase](#can-fd-data-phase)
- [Finding an unknown bitrate](#finding-an-unknown-bitrate)
- [Symptoms of wrong timing](#symptoms-of-wrong-timing)

## The model

A bit is divided into **time quanta (TQ)**. `TQ = BRP / f_clk`, where `f_clk` is the clock that feeds the CAN core and BRP is the prescaler.

| Segment | Length | Purpose |
|---|---|---|
| SYNC_SEG | 1 TQ | where edges are expected |
| PROP_SEG + PHASE_SEG1 (together "TSEG1") | 1-16 TQ on classical controllers | propagation delay allowance, then the sample point |
| PHASE_SEG2 ("TSEG2") | 1-8 TQ | time after the sample point |

```
bitrate      = f_clk / (BRP x (1 + TSEG1 + TSEG2))
sample point = (1 + TSEG1) / (1 + TSEG1 + TSEG2)
```

**SJW** (synchronisation jump width) is how many TQ the controller may stretch or shrink a bit to stay locked to the transmitter. It must not exceed PHASE_SEG2.

Registers almost always store `value - 1`. HAL structs and Linux `ip link` take real values. Mixing the two conventions is the most common off-by-one.

Which clock is `f_clk`:
- MCP2515 and SJA1000: the crystal, with a fixed divide-by-2 (`TQ = 2 x BRP / f_osc`).
- ESP32 TWAI: 80 MHz APB on ESP32/S2/S3/C3; the legacy `brp` field is the total divider and must be even. Newer chips may clock TWAI from the 40 MHz crystal, so do not hard-code.
- STM32 bxCAN: PCLK1 (APB1), which is often half the core clock. STM32 FDCAN: the FDCAN kernel clock selected in RCC.
- MCP2517FD/MCP2518FD: SYSCLK, 40 or 20 MHz (or a 4 MHz crystal with the 10x PLL).

## Choosing values

1. **Exact bitrate first.** Pick a BRP that divides the clock exactly. Total clock tolerance between any two nodes must stay well under 1 %, so a 0.5 % calculation error on top of a ceramic resonator is already too much. Use a crystal for 250 kbit/s and above.
2. **Sample point.** All nodes on a bus should use the same one, within a few percent.

   | Network | Sample point |
   |---|---|
   | CANopen, DeviceNet, general industrial, 500 kbit/s and below | 87.5 % |
   | Automotive 500 kbit/s (SAE J2284), most OEM networks | 80 % (75-81.25 %) |
   | J1939 250 kbit/s | 87.5 % (as close to 7/8 as possible, not later) |
   | 1 Mbit/s | 75-80 % |
   | Joining an existing bus | match the existing nodes; use 80 % for a vehicle if unknown |

   The Linux kernel default is 87.5 % up to 500k, 80 % up to 800k, 75 % above.
3. **More TQ per bit is better** (finer sample-point resolution): 16-20 TQ is typical for classical CAN, 8 is the practical minimum, 10 or more for 1 Mbit/s.
4. **SJW**: set it as large as PHASE_SEG2 allows (up to the controller maximum of 4 on classical parts) unless a network specification says otherwise. Larger SJW tolerates more clock drift.
5. **Bus length**: the propagation segment must cover twice the bus delay (about 5 ns/m) plus transceiver loop delays. Rule of thumb for total bus length: 1 Mbit/s 25-40 m, 500k 100 m, 250k 250 m, 125k 500 m, 50k 1 km.

## Use the calculator

`scripts/can_bit_timing.py` takes, for each prescaler the controller offers, the segment split nearest your sample point, drops anything the controller cannot be programmed with, ranks the rest by bitrate error then sample-point error, and prints register values. If it had to change something you asked for (an SJW larger than phase segment 2 allows), it says so in the output. Run it instead of doing the arithmetic by hand:

```bash
python3 scripts/can_bit_timing.py --profile mcp2515 --clock 8e6 --bitrate 500k --sample-point 80
python3 scripts/can_bit_timing.py --profile twai --clock 80e6 --bitrate 250k
python3 scripts/can_bit_timing.py --profile bxcan --clock 36e6 --bitrate 500k --sample-point 87.5
python3 scripts/can_bit_timing.py --profile mcan --clock 40e6 --bitrate 500k --data-bitrate 2M
python3 scripts/can_bit_timing.py --list-profiles
```

Profiles: `mcp2515`, `sja1000`, `twai`, `bxcan`, `mcan` (STM32 FDCAN, TCAN4550, SAM C21/E5x), `mcp2518fd`, `generic`. "No valid nominal timing" means the clock cannot produce that bitrate exactly (try another clock, or `--max-error 0.2` and judge the result).

On Linux the kernel does this for you: `ip link set can0 type can bitrate 500000 sample-point 0.8`. Check what it chose with `ip -details link show can0`.

## Reference values for common controllers

### MCP2515

`CNF1 = (SJW-1)<<6 | (BRP-1)`, `CNF2 = BTLMODE<<7 | SAM<<6 | (PS1-1)<<3 | (PRSEG-1)`, `CNF3 = (PS2-1)` (bit 7 SOF, bit 6 WAKFIL). Limits: PRSEG 1-8, PS1 1-8, PS2 2-8, SJW 1-4, PRSEG + PS1 >= PS2, PS2 >= SJW (datasheet revision K; earlier revisions said PS2 > SJW, and the library tables below all use SJW 1).

Values used by the popular Arduino libraries (`autowp/arduino-mcp2515`, `coryjfowler/MCP_CAN_lib`). They work on short bench buses, but note the low sample points:

| Crystal | Bitrate | CNF1 | CNF2 | CNF3 | TQ/bit | Sample point |
|---|---|---|---|---|---|---|
| 8 MHz | 125k | 0x01 | 0xB1 | 0x85 | 16 | 62.5 % |
| 8 MHz | 250k | 0x00 | 0xB1 | 0x85 | 16 | 62.5 % |
| 8 MHz | 500k | 0x00 | 0x90 | 0x82 | 8 | 62.5 % |
| 8 MHz | 1M | 0x00 | 0x80 | 0x80 | 4 | 75 % (PS2 = 1 TQ, below the datasheet minimum) |
| 16 MHz | 125k | 0x03 | 0xF0 | 0x86 | 16 | 56.25 % |
| 16 MHz | 250k | 0x41 | 0xF1 | 0x85 | 16 | 62.5 % |
| 16 MHz | 500k | 0x00 | 0xF0 | 0x86 | 16 | 56.25 % |
| 16 MHz | 1M | 0x00 | 0xD0 | 0x82 | 8 | 62.5 % |

A 56-62 % sample point against a vehicle bus designed for 80 % cuts the propagation margin and is a real cause of intermittent errors on longer or noisier buses. Prefer calculated values (`--profile mcp2515`), for example 16 MHz at 500k and 87.5 %: `CNF1=0x00 CNF2=0xAE CNF3=0x01`. For a vehicle bus run the calculator with `--sample-point 80`.

An 8 MHz crystal gives only 4 TQ at 1 Mbit/s: use a 16 MHz or 20 MHz module for 1 Mbit/s.

**Applying custom CNF values.** `autowp/arduino-mcp2515` and `coryjfowler/MCP_CAN_lib` only offer their preset tables: there is no public call that takes raw CNF bytes, so do not invent one. Options:
- `pierremolinaro/acan2515`: `ACAN2515Settings` takes the crystal frequency and bitrate, exposes `mBitRatePrescaler`, `mPropagationSegment`, `mPhaseSegment1`, `mPhaseSegment2`, `mSJW`, and reports the resulting sample point.
- Write the registers yourself while the chip is in configuration mode (it is after reset), then select the operating mode through the library. CNF3, CNF2, CNF1 sit at consecutive addresses 0x28-0x2A:
  ```cpp
  can.reset();                                    // configuration mode
  SPI.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
  digitalWrite(CS_PIN, LOW);
  SPI.transfer(0x02); SPI.transfer(0x28);         // WRITE, starting at CNF3
  SPI.transfer(cnf3); SPI.transfer(cnf2); SPI.transfer(cnf1);
  digitalWrite(CS_PIN, HIGH);
  SPI.endTransaction();
  can.setListenOnlyMode();                        // or setNormalMode(); do not call setBitrate() afterwards
  ```
- Edit the preset table in a local copy of the library.
- On Linux, `ip link set can0 type can bitrate 250000 sample-point 0.875`.

**The crystal on the board must match the value given to the library.** The blue MCP2515 modules usually carry 8 MHz, and most library examples assume 16 MHz. The result is a bitrate that is off by a factor of two: no reception and constant bus errors. Read the marking on the crystal can.

### ESP32 TWAI (legacy driver, 80 MHz)

The ESP-IDF macros `TWAI_TIMING_CONFIG_*()` use 20 TQ and an 80 % sample point: 1M `brp 4`, 500k `brp 8`, 250k `brp 16`, 125k `brp 32`, all with `tseg_1 = 15, tseg_2 = 4, sjw = 3`. Limits: `brp` even 2-128, `tseg_1` 1-16, `tseg_2` 1-8, `sjw` 1-4. On chips where the source clock differs the macros adapt (they are defined through `quanta_resolution_hz` in current IDF). The new driver takes `bit_timing.bitrate` and an optional sample point (`sp_permill`) and computes the rest.

### STM32 bxCAN

`CAN_BTR = (SJW-1)<<24 | (TS2-1)<<20 | (TS1-1)<<16 | (BRP-1)`. Limits: BRP 1-1024, TS1 1-16, TS2 1-8, SJW 1-4. Clock is PCLK1. Examples at 87.5 %: 36 MHz / 500k: Prescaler 4, BS1 15, BS2 2 (18 TQ, 88.9 %) or Prescaler 9, BS1 6, BS2 1 (8 TQ); 42 MHz / 500k: Prescaler 6, BS1 11, BS2 2 (14 TQ, 85.7 %); 48 MHz / 500k: Prescaler 6, BS1 13, BS2 2 (16 TQ, 87.5 %). Confirm with the calculator for your PCLK1.

### M_CAN (STM32 FDCAN, TCAN4550, SAM) and MCP2518FD

Nominal fields are wide (TSEG1 up to 256 TQ), so use BRP = 1 or 2 and many TQ. 40 MHz, 500k at 80 %: BRP 1, TSEG1 63, TSEG2 16, SJW 16. See the next section for the data phase.

## CAN FD data phase

- There are two independent timing sets: nominal (arbitration) and data. Data limits are much tighter (TSEG1 up to 32, TSEG2 up to 16). On M_CAN the data-phase segment 2 is at least 2 TQ, and with transmitter delay compensation on, the data prescaler may only be 1 or 2 (`DBTP.DBRP` 0 or 1). The calculator applies both.
- **Use the same prescaler for both phases** so the TQ length does not change at the bit-rate switch. With a 40 MHz clock, BRP = 1 serves 500k/2M (80 and 20 TQ) and 1M/5M (40 and 8 TQ). A 40 MHz or 80 MHz CAN clock makes this easy; 48 MHz and 36 MHz often cannot hit 5 or 8 Mbit/s exactly.
- Data-phase sample point: 70-80 %. All nodes must agree closely, more so than in the nominal phase.
- **Transmitter delay compensation**: enable for 2 Mbit/s and above. Offset = data-phase sample point in clock periods, `DBRP x (1 + DTSEG1)`; controllers measure the loop delay themselves ("auto" mode). M_CAN: `DBTP.TDC = 1`, `TDCR.TDCO`. MCP2518FD: `CiTDC.TDCMOD = auto`, `TDCO`. STM32 HAL: `HAL_FDCAN_ConfigTxDelayCompensation()` then `HAL_FDCAN_EnableTxDelayCompensation()`. Linux computes it automatically.
- The transceiver must be rated for the data rate (see `transceivers.md`).

## Finding an unknown bitrate

1. Guess from context: OBD-II port pins 6/14 are 500k (some 250k); J1939 is 250k (500k on newer trucks); NMEA 2000 is 250k; CANopen is commonly 125k, 250k, 500k or 1M; body/comfort buses are often 125k or 100k; GM single-wire is 33.3k; 83.3k appears on older Mercedes and some Fiat buses.
2. **Listen-only** and try each candidate. The right one produces frames with no error counters rising. A normal-mode probe at the wrong rate disturbs the bus.
3. Oscilloscope or logic analyser on CANH (or the transceiver RXD pin): the narrowest pulse is one bit. 2 us = 500k, 4 us = 250k, 8 us = 125k, 1 us = 1M.
4. Nothing at all on the bus: it may be asleep (ignition off) or behind a gateway that only answers diagnostic requests.

## Symptoms of wrong timing

| Symptom | Likely cause |
|---|---|
| No frames, error counters rise immediately | wrong bitrate (check the crystal or clock value in code first) |
| Short frames arrive, long or stuffed frames fail | clock error near the tolerance limit: a resonator, or an inexact divider |
| Works on the bench, fails in the vehicle or on a long cable | sample point too early (library defaults), or propagation segment too short |
| Works with one partner device, not another | sample points differ between nodes |
| CAN FD: arbitration fine, data phase errors on transmit only | TDC off or wrong offset |
| CAN FD: data phase errors on receive | data sample point mismatch, transceiver too slow, or ringing from stubs/star topology |
