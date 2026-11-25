# Reverse engineering a CAN bus

How to go from an unknown bus to named, scaled signals. The method is the same for a car, a machine, a battery pack or a motor controller: capture, inventory, then find each signal by the evidence that suits it, fix its scale against something known, and confirm on data it was not fitted to.

Contents
- [Before starting](#before-starting)
- [Choose the method by signal type](#choose-the-method-by-signal-type)
- [Step 1: connect and find the bitrate](#step-1-connect-and-find-the-bitrate)
- [Step 2: capture and inventory](#step-2-capture-and-inventory)
- [Step 3: classify bytes](#step-3-classify-bytes)
- [Step 4a: states and switches, by diffing](#step-4a-states-and-switches-by-diffing)
- [Step 4b: continuous values, by searching against a reference](#step-4b-continuous-values-by-searching-against-a-reference)
- [Getting a reference](#getting-a-reference)
- [Step 5: judging a candidate field](#step-5-judging-a-candidate-field)
- [Step 6: scale and offset](#step-6-scale-and-offset)
- [Step 7: verification is a gate](#step-7-verification-is-a-gate)
- [Signal heuristics](#signal-heuristics)
- [Counters and checksums](#counters-and-checksums)
- [Diagnostic-side reverse engineering](#diagnostic-side-reverse-engineering)
- [Transmitting: replay, injection, gateways](#transmitting-replay-injection-gateways)
- [Safety and legal ground rules](#safety-and-legal-ground-rules)
- [Further reading](#further-reading)

## Before starting

Check whether the work has been done already. It often has.

- **`commaai/opendbc`** (MIT): DBC files for many Toyota, Honda, Hyundai/Kia, GM, Ford, VW, Subaru, Tesla and other platforms, focused on powertrain, chassis and ADAS messages.
- Owner forums and GitHub for the specific platform ("<model> CAN IDs", "<platform> dbc").
- Is it a standard protocol? J1939, NMEA 2000, CANopen and OBD-II need a database or an EDS, not reverse engineering. See the identification table in SKILL.md.
- Industrial and energy equipment makers often supply a CAN matrix on request.

Treat any third-party DBC as a hypothesis: model years and trims differ, and a wrong scale factor looks plausible until checked.

Equipment: a CAN interface with listen-only mode and good timestamps (`tools.md`), a way to reach the right bus (`physical-layer.md`), and ideally an OBD-II reader running at the same time for ground truth.

Work from files, not pasted data. A capture is tens of thousands of frames: keep it on disk, run the scripts on it, and read their summaries. Never load a whole log into the conversation.

## Choose the method by signal type

| Target | Examples | Evidence that finds it | Tool |
|---|---|---|---|
| A state you can switch on demand | door, lock, lights, wipers, gear, buttons | compare a capture with the action against one without | `can_log_analyze.py --diff` |
| A continuous value with something to compare against | speed, rpm, pedal, temperatures, state of charge, steering angle | correlation with a reference value over time | `can_signal_search.py` |
| A continuous value with no reference at all | proprietary sensor with no display or PID | per-bit toggle pattern, then known physical points | `can_log_analyze.py --id`, then calibrate by hand |

Most real jobs use the first two. Decide which before capturing, because they need different captures: a state needs a quiet baseline plus repeated on/off actions; a continuous value needs the quantity to **sweep most of its range** while a reference is recorded.

## Step 1: connect and find the bitrate

1. Identify the bus and tap it without disturbing it: no added termination, short stub.
2. **Listen-only on anything that already works** (a vehicle, a machine): other nodes acknowledge each other and your interface stays silent. The exception is a **single device on a bench** (one sensor or ECU and your interface): nothing else can acknowledge its frames, so in listen-only mode it retransmits forever and its data never updates cleanly. There, use normal mode so your interface ACKs. When unsure, listen-only.
3. Bitrate: try 500k, then 250k, 125k, 1M, 100k, 83.3k, 50k, 33.3k in listen-only; the right one yields frames with no errors (`bit-timing.md`).
4. Nothing at all at any rate: the bus is asleep (turn the ignition on, open a door), you are on the wrong pins, or you are in front of a gateway. Through the OBD port of a gateway vehicle only diagnostic responses appear.
5. Errors only: could be CAN FD on a classical interface (FD frames look like errors), or low-speed fault-tolerant / single-wire CAN on a high-speed transceiver.

## Step 2: capture and inventory

Capture a baseline with everything at rest, then run the analyzer:

```bash
candump -l can0                       # writes candump-<date>.log; or -L to stdout
python3 scripts/can_log_analyze.py baseline.log
```

It prints, per ID: frame count, period and jitter, length, and a per-byte map (constant value, varying, counter, checksum). What to read from it:

- **Period tells importance.** 10-20 ms: powertrain and chassis control (rpm, torque, wheel speeds, steering). 50-100 ms: driver inputs, transmission, body. 200-1000 ms: temperatures, levels, odometer, status. Irregular: event-driven (buttons, diagnostics).
- **ID ordering tells priority**: low IDs are the time-critical ones.
- Frame length under 8 and many constant bytes suggest simple status messages: good first targets.
- On a passenger car, IDs in `0x700`-`0x7FF` (or `18DAxxxx`) are diagnostics, not broadcast data. On a CANopen network the same range is heartbeats (`0x700` + node ID): identify the protocol first.
- The number of distinct IDs (typically 30-150 per vehicle bus) is the size of the job.

**The baseline shows the structure of the bus, not where your signal is.** At rest almost everything is static, the target included, so a pattern in a calm capture is evidence of nothing: eight identical bytes are as likely to be eight idle counters as eight sensors. Form hypotheses from what changes between a calm capture and an exercised one, and from correlation with a reference, never from what a frame looks like.

## Step 3: classify bytes

For one ID, `python3 scripts/can_log_analyze.py capture.log --id 0x244` shows per-byte range and how often each bit toggled.

- **Bit-toggle counts reveal signal boundaries.** Within a numeric signal, the toggle count rises with each step toward the least significant bit, until it levels off at the noise floor. A sudden drop from a busy bit to a quiet one is the boundary between two signals: the quiet bit is the next signal's most significant bit.
- Constant bytes: unused, configuration, or simply not exercised in this capture. Do not conclude "unused" from a parked baseline.
- Bits that flip rarely and independently: flags (doors, lights, switches).
- A byte whose value steps while its neighbour wraps: two halves of a 16-bit value; the analyzer reports the pair and its byte order.
- **Do not assume byte alignment.** Compact frames pack 10-, 11-, 12- and 13-bit fields back to back, sometimes behind a leading flag bit. Reading such a frame as whole bytes mixes neighbouring fields into a value that still correlates with the truth and is still wrong.
- Mark counters and checksums and ignore them from here on.

## Step 4a: states and switches, by diffing

Change exactly one thing and find what changed with it.

```bash
candump -l can0          # 20 s with nothing happening           -> baseline.log
candump -l can0          # 20 s, perform ONE action a few times  -> action.log
python3 scripts/can_log_analyze.py baseline.log --diff action.log
```

The diff lists bytes that took values never seen in the baseline, constant-in-baseline bytes first, with counters and checksums suppressed.

- Hold each state for a couple of seconds and repeat: press, wait 2 s, release, wait 2 s, three times. A real signal shows the same pattern three times; a coincidence does not.
- Expect several hits: the state itself, copies of it in other messages, and consequences (an interior light that stays on after the door closes, a one-off event message). Tell them apart by timing: the state follows your action exactly, consequences lag or linger.
- You operated one door. Whether the bit means "driver's door" or "any door" needs a second capture with a different door.
- If nothing changes, the signal is on another bus, is event-driven and you missed it, or needs ignition/engine state.
- Live alternatives: `cansniffer -c can0`, or SavvyCAN's Sniffer and "Range State" windows.
- **Replay bisection** (bench only; see the transmit rules below): to find which frame *causes* an action, replay the capture; if the action happens, replay half of it, and keep halving. `canplayer -I action.log`.

## Step 4b: continuous values, by searching against a reference

If you can obtain the quantity some other way while capturing, let the script search the fields of every broadcast message against it:

```bash
python3 scripts/can_signal_search.py drive.log                    # which OBD-II PIDs does this capture contain?
python3 scripts/can_signal_search.py drive.log --obd-pid 0D       # find vehicle speed
python3 scripts/can_signal_search.py drive.log --obd-pid 0C       # find engine speed
python3 scripts/can_signal_search.py drive.log --ref-csv gps.csv  # time (s), value from any other source
python3 scripts/can_signal_search.py truck.log --ref-signal "0x18FEF100 8|16@1+ (0.00390625,0)"
```

It scores fields by start bit, length, byte order and sign, settles the field's extent, fits scale and offset, and prints a DBC line with a grade and the evidence. The search is wide, not exhaustive: it skips fields whose end bits never change, masks counters and checksums, ranks IDs on a quick pass before searching the best `--top` of them in full, and does not handle multiplexed messages. It never searches the IDs the reference was read from, and it leaves out the diagnostic range (`0x700`-`0x7FF`, `18DAxxxx`) unless you name IDs with `--ids`, which is how to search a CANopen network.

Reading its output:
- **STRONG CANDIDATE / WEAK CANDIDATE / POOR FIT** grades the fit on the capture it searched, and a field fitted to a capture always looks good on that capture. Even a strong candidate is not a decoded signal until `--check` on another capture says CONFIRMED (step 7). Treat anything weaker as "not found yet".
- Several IDs commonly carry the same quantity: each wheel's speed, a cluster copy, a coarse copy for another module. All of them are real. Choose by update rate and resolution, and note the others.
- `note:` lines mark what the capture could not prove (low bits below the noise floor, top bits that never left zero). Carry those caveats into the DBC comment.
- A warning that the decode agrees when steady but not while changing means the field is wrong, however good the correlation.
- "The reference lags the bus" is normal for polled OBD-II data.

If nothing scores well: the quantity is not broadcast on this bus (common behind a gateway, and for values an ECU only reports on request), the reference did not move enough, or the signal is multiplexed (the script does not handle multiplexed messages: separate the pages by the selector byte first, see `dbc.md`).

## Getting a reference

In order of quality:

1. **An OBD-II PID polled during the same capture.** Same clock, exact values, no human in the loop. Speed, rpm, coolant and intake temperature, throttle, pedal, load, fuel level and battery voltage are available on most cars (`obd2-pids.md`). Poll two or three PIDs at 5-10 Hz while logging everything:
   ```python
   import can, itertools, time                      # logs to file with: candump -l can0 (in another terminal)
   bus = can.Bus(interface="socketcan", channel="can0")
   for pid in itertools.cycle([0x0C, 0x0D]):
       bus.send(can.Message(arbitration_id=0x7DF, is_extended_id=False, data=[2, 1, pid, 0, 0, 0, 0, 0]))
       time.sleep(0.05)
   ```
   Polling is transmitting: it needs a normal-mode interface on the diagnostic port, with the vehicle in a safe state. On a gateway vehicle the OBD port does not show broadcast traffic, so capture on an internal tap (listen-only) while a second interface or a scan tool polls at the OBD port; the requests and responses usually appear on the powertrain bus too. If they do not, log the poller's values with timestamps and use `--ref-csv`.
2. **A signal you can already decode in the same log**: a J1939 parameter, a GPS-to-CAN or sensor-to-CAN module, a signal from a trusted DBC. Use `--ref-signal`.
3. **An external recording**: GPS speed from a phone, a data logger, a dyno. Export time and value to CSV; clocks rarely agree, so expect to set `--ref-time-offset` (the script searches only +/-1 s on its own).
4. **A person**: note the time and the value read from a gauge or display, at several steady levels, and put them in a CSV. Reaction delay and misreadings make this the weakest reference: use many points and trust it for *which field*, less for exact scale.

Two rules for any reference:
- **Sweep to identify, hold to calibrate.** A smooth sweep across the range is what separates the true field from everything else. A handful of held levels cannot: with four or five steps, rolling counters and unrelated values tie with the real signal, and two or three points fit any line. Use held, known levels afterwards to pin the scale.
- **Exclude the reference's own messages from the search**, or it will find itself. The script does this for OBD-II and for `--ref-signal`.

## Step 5: judging a candidate field

Whether found by the script or by hand, test a candidate against what real encodings look like.

- **Byte order**: within a manufacturer it is usually consistent. Big-endian (Motorola) dominates in most European and Asian vehicles and older designs; little-endian (Intel) in J1939, CANopen, Tesla, many newer and non-automotive designs.
- **Signed** if it crosses zero in the middle of its range (steering angle, torque, acceleration, current). Some signals use a sign bit plus magnitude, or an offset instead.
- **It should be smooth.** Decoded frame by frame, a real quantity moves in small steps. Jumps of nearly the full range mean the field starts or ends in the wrong place, has the wrong byte order, or straddles two signals. This holds with no reference at all.
- **Beware the over-wide read.** Two related values often sit side by side: a left/right wheel-speed pair, a value and its redundant copy. Read as one wide field they still correlate almost perfectly, and the decode breaks the first time the two halves differ (a corner, a slipping wheel). Signs: a scale that is a round number divided by 256 or 65536, and no improvement in fit when the extra bytes are added. Prefer the shortest field that fits.
- **Mask "not available" values before fitting.** Many signals send all-ones (`0xFF`, `0xFFFF`) or another far-out value at start-up or when a sensor is absent. Left in, a few such frames wreck a fit. Report that you dropped them.
- Plot the candidate against time (SavvyCAN graph, PlotJuggler, `cantools plot`). A real signal looks like the physical quantity; a wrong byte order looks like a sawtooth; a wrong length shows discontinuities.

## Step 6: scale and offset

`physical = raw x scale + offset`.

- Fit against the reference (the script does), or against two or more known points: engine off (0 rpm), stationary (0 km/h), battery voltage against a multimeter, full and empty sweeps (0-100 %), ambient temperature after a cold soak, steering centred and at the stops.
- **Engineers choose round numbers.** Scales: 1, 0.5, 0.25, 0.125, 0.1, 0.01, 0.001, 1/256, 0.0625, 0.03125. Offsets: 0, -40, -48, -273, half of range. A fit that lands on 0.0997 means 0.1. A fit that lands on 0.000386 and nowhere near a round value more likely means the wrong field than an odd engineer.
- Round only when it barely moves the decode (under about 1 % of range). A rounding that shifts results by several percent hides a real disagreement, for example a dashboard speed that deliberately reads high against true speed.
- **A decode must be right at a known state.** Correlation is blind to a constant offset: a field can score 0.999 and still read -1.6 km/h when parked. Zero at rest (speed, current, flow, torque) is the strongest single check available. A small miss is fixed by the offset; a large one means the field is wrong.
- In the DBC, give `[min|max]` as the range the bits can represent (`raw 0 .. 2^length - 1` through the formula), not the range the capture happened to contain.

## Step 7: verification is a gate

A candidate can correlate with the reference, and decode correctly at a few calibration points, and still be the wrong field.

```bash
python3 scripts/can_signal_search.py other-drive.log --obd-pid 0D --check "0x1A0 4|12@1+ (0.1,0)"
```

- **Identify on one capture, check on another.** A field that was fitted to a capture will always look good on it. `--check` scores a finished definition against a reference on a different capture and exits non-zero unless it is CONFIRMED.
- The classic failure is agreement while steady and disagreement while changing. Do not explain a poor result as "the reference was noisy": for the right field, both agree.
- If results stay ambiguous, capture again with a *different* excitation (slower, faster, wider) and require the same field to win.
- Write the signal into a DBC file immediately (`dbc.md`), with a comment saying how it was verified, on which vehicle or firmware, and any caveat the search reported. Unlabelled notes get lost and unverified guesses get trusted.
- Decode live with `cantools monitor -c can0 file.dbc` or in SavvyCAN to watch it behave.

## Signal heuristics

| Quantity | Typical encoding |
|---|---|
| Engine speed | 16 bits, 0.25 or 0.125 or 1 rpm/bit, 10-20 ms message |
| Vehicle speed | 16 bits (often 13-15 used), 0.01 km/h per bit; sometimes mph x 100 or 1/128, 1/256 km/h |
| Wheel speeds | four 13-16 bit values in one or two messages, 0.01-0.0625 km/h per bit, sometimes with an offset |
| Steering angle | 16 bits signed, 0.1 deg/bit (also 0.04375 or 1/16); rate signal nearby |
| Pedals, throttle | 8 bits, 0.4 % or 0.5 %/bit; or 10-12 bits |
| Brake pressure | 8-12 bits, alongside a brake-switch flag |
| Temperatures | 8 bits, 1 degC/bit offset -40 (or -48); 0.75 degC/bit - 48 in VW group |
| Battery voltage | 8 bits at 0.1 V or 16 bits at 0.001-0.01 V |
| HV battery voltage / current | 16 bits, 0.1 V; current signed or offset, 0.1 A |
| State of charge | 8 bits 0.5 %/bit, or 10 bits 0.1 % |
| Gear, drive mode | 3-4 bit enumeration |
| Doors, lights, indicators, belts | single bits, grouped in one or two body messages |
| Odometer | 20-32 bits, 1 km or 0.1 km per bit, slow message |
| Time, date | BCD or plain bytes, 1 s message |
| Torque | 11-16 bits signed or offset, 0.5-1 Nm/bit |
| Accelerations, yaw rate | 10-16 bits with a mid-range offset |

## Counters and checksums

Safety-related messages carry a rolling counter and a checksum so receivers can detect stale or corrupted frames.

- Counter: typically 4 bits (0-15, sometimes 0-14 or 2 bits), incrementing each transmission. Often the low nibble of the second-to-last byte or of the checksum's neighbour.
- Checksum: usually the last or first byte. Common schemes, all tested by `can_log_analyze.py`: XOR of the other bytes; sum of the other bytes (plain, inverted or negated); sum including the CAN ID bytes and length (Toyota); CRC-8 SAE J1850 (polynomial 0x1D); CRC-8 polynomial 0x2F (AUTOSAR); CRC-8 polynomial 0x07.
- Not detected automatically: 4-bit checksums (Honda: a nibble sum over ID and data), CRCs with a per-message secret constant appended (VW MQB, many AUTOSAR E2E profiles), and CRCs over a reordered byte sequence. For those, look at opendbc, whose per-brand checksum functions are public, or gather many frames and test hypotheses with the CRC RevEng tool.
- A checksum-like byte is a hint, not a verdict: the busy low byte of a wide signal can resemble one. A byte that the diff or the search ties to a physical quantity is a signal.
- SecOC-authenticated messages carry a truncated MAC that cannot be derived from captures.

Why it matters: to transmit a protected message you must compute a valid counter and checksum; replaying an old frame fails the counter check.

## Diagnostic-side reverse engineering

Much data never appears in broadcast traffic but can be read by request (`uds.md`).

1. Sniff a capable scan tool. Capture while the tool shows the value you want, then `python3 scripts/isotp_decode.py capture.log`. Each request/response pair is listed with service and identifier. Change the value on the vehicle and see which response bytes follow.
2. Without a tool: enumerate ECUs and DIDs (see "Finding ECUs and identifiers" in `uds.md`), then correlate response bytes against known values.
3. Through an ELM327-style adapter, the result is a "custom PID": header, request bytes and an equation.

Diagnostic polling has a cost: each value is a request, so update rates are a few Hz, and it adds traffic. Prefer broadcast signals where they exist.

## Transmitting: replay, injection, gateways

Reading is passive. Transmitting changes the system: plan it.

- **ID conflicts**: if you transmit an ID that an ECU also transmits, both versions reach the receivers and the two transmitters can collide into error frames. Receivers see alternating values. To replace a message you must stop the original reaching the receiver: a **man-in-the-middle bridge** with two CAN interfaces, cut into the wiring between the sender and the rest of the bus, forwarding everything except the frames you modify (Linux `cangw`, or a dual-CAN microcontroller).
- Adding a new ID that nobody else sends avoids a collision with an existing message, but it is not harmless: it adds bus load, a gateway may forward or log it, and an ECU may act on an ID you did not know it listens to. Most ECUs ignore IDs they do not expect, which is also why an invented ID rarely does anything useful.
- Honour counters and checksums, and the message period: receivers flag timeouts and implausible data as faults (and store DTCs).
- Flooding a low ID starves the rest of the bus; a transmit error at the wrong bitrate can take the bus down.
- Simulating a missing module (so the rest of the network stops complaining) is a common, legitimate use: reproduce its periodic messages with valid counters at the right rate.
- Practise on a simulator first: `ICSim` (instrument cluster simulator on `vcan0`) reproduces the whole workflow with no hardware.

## Safety and legal ground rules

- Work on equipment you own or are authorised to test.
- **Sniffing in listen-only is safe. Transmitting is not automatically safe.** Never transmit on powertrain, chassis or ADAS buses of a moving vehicle. Random fuzzing, of IDs or of diagnostic services, belongs only on a bench ECU or a simulator, never on a complete vehicle. Sending a specific frame you have already observed (replaying a door-lock command, simulating a missing module) can be done on a stationary vehicle once you have checked that the user is authorised, which bus it goes to, and that nothing it could move can hurt anyone: parked, wheels off the ground if the powertrain could respond, someone at the controls.
- Captures that need the vehicle moving (speed, wheel speeds) are made by a passenger or an unattended logger, never by the driver operating a laptop.
- Fuzzing random IDs or diagnostic services can set faults, deploy actuators, corrupt configuration or brick an ECU. Never fuzz a vehicle someone depends on.
- Keep a battery maintainer on during long ignition-on sessions; low voltage causes cascades of faults.
- Expect spurious DTCs after experiments. Read and save the stored codes before clearing any, so that a real fault is not erased with them, and remember that clearing engine codes resets emissions readiness.
- Emissions controls, odometer values, immobilisers and safety systems are regulated: changing them is illegal in most jurisdictions regardless of ownership. Do not help defeat them.
- In the US, DMCA section 1201 exemptions permit circumvention for diagnosis, repair, lawful modification and good-faith security research on vehicles one owns; other countries differ, and warranties and insurance have their own terms.
- Security findings on products should go to the manufacturer through coordinated disclosure.

## Further reading

- Craig Smith, *The Car Hacker's Handbook* (No Starch Press; readable free at opengarages.org): the standard introduction.
- CSS Electronics, "CAN bus reverse engineering with AI" and the `CSS-Electronics/can-bus-reverse-engineering-skills` repository (MIT): a reference-driven workflow for their CANsub interface, with a human-input and a video-OCR reference. Several ideas in steps 4b to 7 follow that work.
- Miller and Valasek's published research papers on vehicle network analysis.
- Marchetti and Stabili, "READ: Reverse Engineering of Automotive Data Frames" (2018); Pesé et al., "LibreCAN" (2019): automated signal extraction.
- CSS Electronics' free guides on CAN, OBD-II, UDS, J1939, CANopen and DBC.
- `commaai/opendbc` for worked DBC files and checksum implementations.
