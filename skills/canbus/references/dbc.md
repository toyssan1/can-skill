# DBC files and signal encoding

A DBC file is the de facto standard text format describing how to turn CAN frames into named, scaled signals. Every serious tool reads it. `assets/template.dbc` is a small valid file (checked with cantools) to copy from.

Contents
- [File structure](#file-structure)
- [The signal line](#the-signal-line)
- [Bit numbering and byte order](#bit-numbering-and-byte-order)
- [Decoding a signal in code](#decoding-a-signal-in-code)
- [Message IDs and extended frames](#message-ids-and-extended-frames)
- [Multiplexed signals](#multiplexed-signals)
- [Value tables, comments, attributes](#value-tables-comments-attributes)
- [Checking a DBC](#checking-a-dbc)
- [Other database formats](#other-database-formats)
- [Where DBC files come from](#where-dbc-files-come-from)

## File structure

```
VERSION ""
NS_ :
BS_:
BU_: ECM BCM TOOL                          <- node names

BO_ 201 ENGINE_1: 8 ECM                    <- message: decimal ID, name, length in bytes, sender
 SG_ EngineSpeed : 7|16@0+ (0.25,0) [0|16383.75] "rpm" TOOL
 SG_ Counter : 32|4@1+ (1,0) [0|15] "" TOOL

CM_ SG_ 201 EngineSpeed "comment";
BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;
BA_ "GenMsgCycleTime" BO_ 201 10;
VAL_ 947 GearSelected 0 "P" 1 "R" 2 "N" 3 "D" ;
```

Rules to write by: indent each signal line by one space under its `BO_` line (what every tool writes; most parsers tolerate other whitespace); names are C identifiers (no spaces, not starting with a digit); `VERSION`, `NS_`, `BS_` and `BU_` come first; message IDs are **decimal**; `CM_`, `BA_DEF_`, `BA_DEF_DEF_`, `BA_`, `VAL_` and `VAL_TABLE_` statements end with `;`, while `VERSION`, `BU_`, `BO_` and `SG_` lines do not. Use `Vector__XXX` as the node name when the sender or receiver is unknown.

## The signal line

```
SG_ Name : start|length@order sign (factor,offset) [min|max] "unit" Receivers
```

| Part | Meaning |
|---|---|
| `start` | start bit (see the next section: its meaning depends on byte order) |
| `length` | length in bits |
| `@1` / `@0` | `@1` little-endian (Intel), `@0` big-endian (Motorola) |
| `+` / `-` | unsigned / signed (two's complement) |
| `(factor,offset)` | `physical = raw x factor + offset` |
| `[min|max]` | physical range, informational. `[0|0]` means unspecified |
| `"unit"` | free text |
| `Receivers` | comma-separated node names |

Floating-point signals keep a normal `SG_` line (32 or 64 bits) and add `SIG_VALTYPE_ <id> <signal> : 1;` (1 = float, 2 = double).

## Bit numbering and byte order

Bits are numbered across the frame with **bit 0 = least significant bit of byte 0**, bit 7 = most significant bit of byte 0, bit 8 = least significant bit of byte 1, and so on: `bit = 8 x byte + bit_in_byte`.

- **Little-endian (`@1`)**: `start` is the signal's **least significant bit**. The signal grows toward higher bit numbers. A 16-bit value in bytes 2-3 is `16|16@1+`.
- **Big-endian (`@0`)**: `start` is the signal's **most significant bit**, in the same numbering. The signal runs down to bit 0 of that byte and continues at bit 7 of the next byte. A 16-bit value in bytes 0-1 is `7|16@0+`; in bytes 2-3 it is `23|16@0+`. A 12-bit value whose top 4 bits are the low nibble of byte 1 and whose low 8 bits are byte 2 is `11|12@0+`.

The big-endian convention is the classic source of off-by-a-byte errors: the start bit of a byte-aligned Motorola signal is `8 x first_byte + 7`, not `8 x first_byte`.

For a single byte both forms are equivalent: `16|8@1+` and `23|8@0+` describe byte 2.

Some tools and documents state big-endian positions by the least significant bit instead ("Motorola LSB" or "backward" notation). Convert before writing the DBC:

```python
def motorola_lsb_from_dbc(start, length):       # 7|16 -> 8 ; 11|12 -> 16
    byte, bit = divmod(start, 8)
    pos = byte * 8 + (7 - bit) + length - 1     # position in transmission order, 0 = first bit of byte 0
    return (pos // 8) * 8 + (7 - pos % 8)
```

Check any layout with `cantools dump file.dbc`, which draws the bit grid of every message.

## Decoding a signal in code

```python
def extract(data: bytes, start: int, length: int, little_endian: bool, signed: bool = False) -> int:
    """Raw value of a DBC-style signal. start uses DBC numbering for the given byte order."""
    if little_endian:
        raw = (int.from_bytes(data, "little") >> start) & ((1 << length) - 1)
    else:
        byte, bit = divmod(start, 8)
        first = byte * 8 + (7 - bit)                                   # MSB position in transmission order
        raw = (int.from_bytes(data, "big") >> (len(data) * 8 - first - length)) & ((1 << length) - 1)
    if signed and raw >> (length - 1):
        raw -= 1 << length
    return raw

# physical = extract(...) * factor + offset
# extract(bytes.fromhex("0BB8405A05000099"), 7, 16, False) -> 0x0BB8 ; x 0.25 = 750 rpm
```

In C for a fixed layout, shift and mask directly: big-endian 16-bit in bytes 0-1 is `(d[0] << 8) | d[1]`; little-endian is `d[0] | (d[1] << 8)`; cast to `int16_t` for signed. For more than a handful of signals, generate the code with `cantools generate_c_source` instead of hand-writing it.

## Message IDs and extended frames

- The `BO_` ID is decimal. An 11-bit ID is written as is: `0x0C9` is `201`.
- A **29-bit ID has bit 31 set** to mark it extended: `0x18FEEEFE | 0x80000000 = 0x98FEEEFE = 2566844158`. Forgetting this makes tools treat it as an (impossible) standard ID and never match.
- J1939 databases are written with a placeholder source address (usually `0xFE`) and carry attributes (`ProtocolType` = `J1939`, `VFrameFormat` = `J1939PG`) telling tools to match on the PGN only, ignoring priority and source address. A tool that ignores those attributes matches nothing unless the source address happens to equal the placeholder: mask the ID yourself in that case.
- CAN FD messages are marked through the `VFrameFormat` attribute and may be up to 64 bytes long.
- `BO_ 3221225472 VECTOR__INDEPENDENT_SIG_MSG` is a Vector placeholder for unassigned signals: ignore it.

## Multiplexed signals

One message ID carries different content depending on a selector field, common in battery data and diagnostics-style broadcast messages.

```
BO_ 1200 MUX_EXAMPLE: 8 ECM
 SG_ Page M : 0|8@1+ (1,0) [0|255] "" TOOL                 <- M: the multiplexer
 SG_ CellVoltage1 m0 : 8|16@1+ (0.001,0) [0|65.535] "V" TOOL   <- present when Page == 0
 SG_ CellTemp1 m1 : 8|8@1+ (1,-40) [-40|215] "degC" TOOL       <- present when Page == 1
```

Signals without a marker are always present. Nested multiplexing uses `m0M` plus `SG_MUL_VAL_` lines (extended multiplexing); not every tool supports it.

Spotting multiplexing in a capture: one byte cycles through a small set of values and the rest of the payload changes character with it. Group frames by that byte before analysing the others.

## Value tables, comments, attributes

```
VAL_ 947 GearSelected 0 "P" 1 "R" 2 "N" 3 "D" ;                  enumerations
CM_ SG_ 201 EngineSpeed "Verified against OBD PID 0C, <date>";    signal comment
CM_ BO_ 201 "10 ms powertrain message";                           message comment
BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;                        attribute definition
BA_DEF_DEF_ "GenMsgCycleTime" 0;                                  its default
BA_ "GenMsgCycleTime" BO_ 201 10;                                 cycle time in ms for message 201
```

Record in comments how each reverse-engineered signal was verified and on what vehicle or firmware. Mark unconfirmed signals as such in the name or comment.

## Checking a DBC

```bash
cantools dump file.dbc                                   # parses, prints layouts; errors show the line
candump can0 | cantools decode file.dbc                  # live sanity check
cantools decode file.dbc < capture.log
```

Common mistakes: hex or missing-bit-31 IDs; Motorola start bits computed as LSB; overlapping signals; length exceeding the message; a factor of 0; tab indentation; non-ASCII characters in names; forgetting the trailing `;` on `VAL_` lines.

## Other database formats

| Format | What it describes |
|---|---|
| KCD | open XML equivalent of DBC (Kayak) |
| SYM | PEAK's text format |
| ARXML | AUTOSAR system description: frames, PDUs, signals, E2E and SecOC settings |
| LDF | LIN bus |
| EDS / DCF / XDD | CANopen object dictionaries |
| A2L | XCP/CCP measurement and calibration variables with memory addresses |
| ODX / PDX, CDD | diagnostic data: services, DIDs, DTC texts |
| J1939 Digital Annex | SAE's spreadsheet of PGNs and SPNs |

`canmatrix` and `cantools convert` translate between most of the signal-database formats.

## Where DBC files come from

- The manufacturer: under NDA for vehicles, often freely for industrial and energy products.
- `commaai/opendbc` (MIT) for many passenger vehicles, with generators and per-brand checksum code.
- Standards bodies and resellers for J1939 and NMEA 2000.
- Community repositories per platform, of varying quality.
- Your own reverse engineering (`reverse-engineering.md`).

A DBC from any source other than the manufacturer for your exact vehicle is a starting point: check at least one signal per message against reality before trusting the rest.
