#!/usr/bin/env python3
"""CAN capture analyzer for reverse engineering.

Reads candump logs (`candump -l` / `-L` files and console output), bare
`ID#DATA` lines, and SavvyCAN/GVRET CSV, then answers the three questions RE work keeps asking:

  1. What is on this bus?          can_log_analyze.py capture.log
  2. What is inside one message?   can_log_analyze.py capture.log --id 0x244
  3. What changed when I did X?    can_log_analyze.py baseline.log --diff action.log

Summary byte map legend:  3F = constant value   ~~ = varies   cn = rolling counter
                          ck = checksum/CRC over the other bytes

Add --j1939 to label 29-bit IDs with priority / PGN / source address.

Standard library only. Python 3.8+.
"""
import argparse
import re
import statistics
import sys
from collections import defaultdict, namedtuple

# bus: the interface name (candump) or bus number (CSV), "" when the line has none.
# timed: False when the file had no timestamps; ts then only preserves frame order.
Frame = namedtuple("Frame", "ts can_id ext data bus timed", defaults=("", True))

# The timestamp and interface are optional so that bare "123#DEADBEEF" lines (cansend syntax) also parse.
RE_LOG = re.compile(r"^\s*(?:\((\d+\.\d+)\)\s+(\S+)\s+)?([0-9A-Fa-f]{3,8})#(#?)(\S*)")
RE_CONSOLE = re.compile(
    r"^\s*(?:\((\d+\.\d+)\)\s+)?(\S+)\s+(?:[TR]X\s+[-BE]\s+[-BE]\s+)?([0-9A-Fa-f]{3,8})\s+\[(\d+)\]\s*((?:[0-9A-Fa-f]{2}\s*)*)")

ERR_FLAG = 0x20000000


def read_frames(path):
    """Yield Frame for every data frame in the file. Error frames, remote frames and lines whose data does
    not match their stated length (a truncated line) are skipped."""
    with open(path, "r", errors="replace") as fh:
        csv_mode = False
        n = 0
        for line in fh:
            if not line.strip():
                continue
            if line.lower().startswith("time stamp,id,extended"):
                csv_mode = True
                continue
            if csv_mode:
                p = [x.strip() for x in line.split(",")]
                try:
                    dlc = int(p[5])
                    data = bytes(int(x, 16) for x in p[6:6 + dlc] if x)
                    if len(data) == dlc:
                        yield Frame(int(p[0]) / 1e6, int(p[1], 16), p[2].lower() == "true", data, p[4])
                except (ValueError, IndexError):
                    pass
                continue
            m = RE_LOG.match(line)
            if m:
                ts, bus, ident, fd, payload = m.groups()
                if fd:
                    payload = payload[1:]  # drop the CAN FD flags nibble
                if payload[:1] in ("R", "r"):
                    continue
                payload = payload.replace(".", "").split("_")[0]
                try:
                    data = bytes.fromhex(payload)
                except ValueError:
                    continue
            else:
                m = RE_CONSOLE.match(line)
                if not m or "remote" in line.lower():
                    continue
                ts, bus, ident, dlc, payload = m.groups()
                data = bytes.fromhex(payload.replace(" ", ""))
                if len(data) != int(dlc):
                    continue
            timed = ts is not None
            if not timed:
                ts, n = n / 1000.0, n + 1  # no timestamps: keep the order only
            can_id = int(ident, 16)
            ext = len(ident) > 3
            if ext and can_id & ERR_FLAG:
                continue
            yield Frame(float(ts), can_id & 0x1FFFFFFF, ext, data, bus or "", timed)


def load(path, bus=None):
    """All frames of one bus, as a list. Exits with a one-line message when the file cannot be read or holds
    more than one bus and none was chosen: frames from two buses must never be analysed as one."""
    try:
        frames = list(read_frames(path))
    except OSError as e:
        sys.exit(f"error: cannot read {path}: {e.strerror}")
    buses = sorted({f.bus for f in frames})
    if bus is not None:
        frames = [f for f in frames if f.bus == bus]
        if not frames:
            sys.exit(f"error: no frames from bus '{bus}' in {path} (buses in the file: "
                     f"{', '.join(repr(b) for b in buses) or 'none'})")
    elif len(buses) > 1:
        sys.exit(f"error: {path} holds frames from {len(buses)} buses ({', '.join(repr(b) for b in buses)}). "
                 f"They are separate networks: pick one with --bus NAME")
    return frames


# --------------------------------------------------------------------------- checksums

def _crc8(poly, init, xorout):
    def f(buf):
        crc = init
        for b in buf:
            crc ^= b
            for _ in range(8):
                crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        return crc ^ xorout
    return f


def _xor(buf):
    x = 0
    for b in buf:
        x ^= b
    return x


def _id_bytes(can_id):
    return [(can_id >> s) & 0xFF for s in (24, 16, 8, 0) if can_id >> s or s == 0]


# name -> f(other_bytes, can_id, dlc). "other bytes" excludes the checksum byte itself.
CHECKSUMS = {
    "XOR of other bytes": lambda o, i, n: _xor(o),
    "sum of other bytes": lambda o, i, n: sum(o) & 0xFF,
    "inverted sum (~sum)": lambda o, i, n: ~sum(o) & 0xFF,
    "two's complement sum (-sum)": lambda o, i, n: -sum(o) & 0xFF,
    "sum of other bytes + CAN ID bytes + DLC (Toyota style)": lambda o, i, n: (sum(o) + sum(_id_bytes(i)) + n) & 0xFF,
    "CRC-8 SAE J1850 (poly 0x1D, init 0xFF, xorout 0xFF)": lambda o, i, n, f=_crc8(0x1D, 0xFF, 0xFF): f(o),
    "CRC-8 poly 0x1D, init 0x00": lambda o, i, n, f=_crc8(0x1D, 0, 0): f(o),
    "CRC-8 AUTOSAR 8H2F (poly 0x2F, init 0xFF, xorout 0xFF)": lambda o, i, n, f=_crc8(0x2F, 0xFF, 0xFF): f(o),
    "CRC-8 poly 0x07, init 0x00": lambda o, i, n, f=_crc8(0x07, 0, 0): f(o),
}


def find_checksum(can_id, payloads):
    """Return (byte_position, algorithm) if the first or last byte is a checksum of the rest."""
    uniq = list({p for p in payloads})
    if len(uniq) < 16:
        return None
    n = len(uniq[0])
    if n < 3 or any(len(p) != n for p in uniq):
        return None
    for pos in (n - 1, 0):
        if len({p[pos] for p in uniq}) < 4:
            continue
        for name, fn in CHECKSUMS.items():
            if all(fn(p[:pos] + p[pos + 1:], can_id, n) == p[pos] for p in uniq):
                return pos, name
    return None


# --------------------------------------------------------------------------- counters

COUNTER_FIELDS = [(0, 8, "byte"), (0, 4, "low nibble"), (4, 4, "high nibble"),
                  (6, 2, "bits 7-6"), (4, 2, "bits 5-4")]


def find_counter(series):
    """series: values of one byte position over time. Returns a field description or None."""
    if len(series) < 20:
        return None
    for shift, width, label in COUNTER_FIELDS:
        mod = 1 << width
        vals = [(v >> shift) & (mod - 1) for v in series]
        if len(set(vals)) < min(mod, 4):
            continue
        hits = sum(1 for a, b in zip(vals, vals[1:]) if (b - a) % mod == 1)
        if hits >= 0.95 * (len(vals) - 1):
            return label
    return None


# --------------------------------------------------------------------------- J1939

J1939_PGNS = {
    59392: "ACK", 59904: "Request", 60160: "TP.DT", 60416: "TP.CM", 60928: "Address Claimed",
    61441: "EBC1", 61442: "ETC1", 61443: "EEC2", 61444: "EEC1", 61445: "ETC2",
    65132: "TCO1", 65217: "VDHR", 65226: "DM1", 65248: "VD", 65253: "HOURS", 65257: "LFC",
    65260: "VI", 65262: "ET1", 65263: "EFL/P1", 65265: "CCVS1", 65266: "LFE1", 65269: "AMB",
    65270: "IC1", 65271: "VEP1", 65272: "TRF1", 65276: "DD",
}


def j1939_fields(can_id):
    """29-bit ID -> (priority, pgn, destination or None, source)."""
    prio = (can_id >> 26) & 7
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    dp = (can_id >> 24) & 3
    if pf < 240:  # PDU1: PS is a destination address and is not part of the PGN
        return prio, (dp << 16) | (pf << 8), ps, can_id & 0xFF
    return prio, (dp << 16) | (pf << 8) | ps, None, can_id & 0xFF


# --------------------------------------------------------------------------- analysis

def group(frames):
    by_id = defaultdict(list)
    for f in frames:
        by_id[(f.can_id, f.ext)].append(f)
    return by_id


def fmt_id(can_id, ext):
    return f"{can_id:08X}" if ext else f"{can_id:03X}"


def column(frames, pos):
    return [f.data[pos] for f in frames if len(f.data) > pos]


def classify(can_id, frames):
    """Per-byte tags for one ID, plus notes."""
    width = max(len(f.data) for f in frames)
    tags, notes = [], []
    ck = find_checksum(can_id, [f.data for f in frames])
    for pos in range(width):
        col = column(frames, pos)
        if len(set(col)) == 1:
            tags.append(f"{col[0]:02X}")
        elif ck and ck[0] == pos:
            tags.append("ck")
            notes.append(f"byte {pos}: {ck[1]}")
        else:
            cnt = find_counter(col)
            if cnt:
                tags.append("cn")
                notes.append(f"byte {pos}: counter in {cnt}")
            else:
                tags.append("~~")
    return tags, notes


def period_stats(frames):
    gaps = [b.ts - a.ts for a, b in zip(frames, frames[1:])]
    if not gaps or not frames[0].timed:   # no timestamps in the file: a period would be invented
        return None, None
    med = statistics.median(gaps)
    jit = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    return med * 1000, jit * 1000


def summary(by_id, j1939=False, min_count=1):
    total = sum(len(v) for v in by_id.values())
    ts = [f.ts for v in by_id.values() for f in (v[0], v[-1])]
    span = max(ts) - min(ts) if ts else 0
    if all(v[0].timed for v in by_id.values()):
        out = [f"{total} frames, {len(by_id)} IDs, {span:.1f} s"
               + (f", {total / span:.0f} frames/s" if span > 0 else "")]
    else:
        out = [f"{total} frames, {len(by_id)} IDs. The file has no timestamps: frame order is known, "
               f"periods and rates are not."]
    cols = f"{'count':>7}  {'period ms':>9}  {'jitter':>7}  {'len':>3}  bytes"
    if j1939:
        cols = f"{'P':>1} {'PGN':>6} {'SA':>3} {'name':<8}  " + cols
    out.append(f"{'ID':>8}  {cols}")
    notes_all = []
    for (can_id, ext), frames in sorted(by_id.items()):
        if len(frames) < min_count:
            continue
        tags, notes = classify(can_id, frames)
        med, jit = period_stats(frames)
        lens = sorted({len(f.data) for f in frames})
        per = f"{med:9.1f}  {jit:7.1f}" if med is not None else f"{'-':>9}  {'-':>7}"
        ident = fmt_id(can_id, ext)
        row = f"{len(frames):>7}  {per}  {'/'.join(map(str, lens)):>3}  {' '.join(tags)}"
        if j1939 and ext:
            p, pgn, _da, sa = j1939_fields(can_id)
            row = f"{p:>1} {pgn:>6} {sa:>3} {J1939_PGNS.get(pgn, ''):<8}  " + row
        elif j1939:
            row = " " * 22 + row
        out.append(f"{ident:>8}  {row}")
        notes_all += [f"  {ident} {n}" for n in notes]
    if notes_all:
        out.append("\nDetected structure:")
        out += notes_all
    return "\n".join(out)


def carry_pairs(frames, width):
    """Adjacent byte pairs that behave like one 16-bit value: low byte wraps when high byte steps."""
    found = []
    for hi, lo, order in [(i, i + 1, "big-endian (Motorola)") for i in range(width - 1)] + \
                         [(i + 1, i, "little-endian (Intel)") for i in range(width - 1)]:
        steps = carries = 0
        prev = None
        for f in frames:
            if len(f.data) <= max(hi, lo):
                continue
            cur = (f.data[hi], f.data[lo])
            if prev and cur[0] != prev[0]:
                dh = (cur[0] - prev[0]) % 256
                if dh in (1, 255):
                    steps += 1
                    # an up-step should see the low byte fall, a down-step should see it rise
                    if (dh == 1 and cur[1] < prev[1]) or (dh == 255 and cur[1] > prev[1]):
                        carries += 1
            prev = cur
        if steps >= 3 and carries >= 0.8 * steps:
            found.append(f"bytes {min(hi, lo)}-{max(hi, lo)}: 16-bit {order} "
                         f"({carries}/{steps} high-byte steps coincide with a low-byte wrap)")
    return found


def detail(by_id, want):
    keys = [k for k in by_id if k[0] == want]
    if not keys:
        return None
    out = []
    for key in keys:
        frames = by_id[key]
        can_id, ext = key
        width = max(len(f.data) for f in frames)
        med, jit = period_stats(frames)
        out.append(f"ID {fmt_id(can_id, ext)}: {len(frames)} frames"
                   + (f", period {med:.1f} ms (jitter {jit:.1f})" if med is not None else ""))
        if ext:
            p, pgn, da, sa = j1939_fields(can_id)
            out.append(f"  if J1939: priority {p}, PGN {pgn} (0x{pgn:05X}) {J1939_PGNS.get(pgn, '')}, "
                       f"SA {sa}" + (f", DA {da}" if da is not None else ""))
        tags, notes = classify(can_id, frames)
        out.append("  byte  tag  uniq  min  max   bit flips 7..0 (how often each bit toggled)")
        for pos in range(width):
            col = column(frames, pos)
            flips = [sum(1 for a, b in zip(col, col[1:]) if (a ^ b) >> bit & 1) for bit in range(7, -1, -1)]
            out.append(f"  {pos:>4}  {tags[pos]:>3}  {len(set(col)):>4}   {min(col):02X}   {max(col):02X}   "
                       + " ".join(f"{x:>5}" for x in flips))
        for n in notes + carry_pairs(frames, width):
            out.append("  " + n)
        out.append("  Reading the flip counts: within one signal the toggle count rises towards the least "
                   "significant bit. A sharp drop marks a signal boundary. Bits that never flip are unused, "
                   "constant, or simply not exercised in this capture.")
        seen, shown = set(), 0
        out.append("  first distinct payloads:")
        for f in frames:
            if f.data not in seen:
                seen.add(f.data)
                out.append(f"    {f.ts:.3f}  {f.data.hex(' ').upper()}")
                shown += 1
                if shown == 12:
                    break
        out.append(f"  ({len({f.data for f in frames})} distinct payloads in total)")
    return "\n".join(out)


def diff(base, act):
    out = []
    new_ids = sorted(set(act) - set(base))
    gone = sorted(set(base) - set(act))
    if new_ids:
        out.append("IDs only in the action capture: " + ", ".join(fmt_id(*k) for k in new_ids))
    if gone:
        out.append("IDs only in the baseline: " + ", ".join(fmt_id(*k) for k in gone))
    rows = []
    for key in sorted(set(base) & set(act)):
        can_id, ext = key
        tags, _ = classify(can_id, base[key])
        width = max(max(len(f.data) for f in base[key]), max(len(f.data) for f in act[key]))
        for pos in range(width):
            tag = tags[pos] if pos < len(tags) else "~~"
            if tag in ("cn", "ck"):
                continue  # counters and checksums always produce new values: noise
            b, a = set(column(base[key], pos)), set(column(act[key], pos))
            novel = sorted(a - b)
            if not novel:
                continue
            mask = 0
            for v in novel:
                for old in b or {0}:
                    mask |= v ^ old
            # bits that only ever differ from every baseline value
            base_var = 0
            bl = sorted(b)
            for v in bl[1:]:
                base_var |= v ^ bl[0]
            rows.append((0 if tag != "~~" else 1, fmt_id(can_id, ext), pos, tag,
                         " ".join(f"{v:02X}" for v in novel[:8]) + (" ..." if len(novel) > 8 else ""),
                         mask & ~base_var & 0xFF))
    if rows:
        out.append("\nBytes that took values never seen in the baseline "
                   "(constant-in-baseline bytes first: these are the best candidates):")
        out.append(f"  {'ID':>8}  byte  baseline  new values                 newly active bits")
        for _, ident, pos, tag, novel, bits in sorted(rows):
            out.append(f"  {ident:>8}  {pos:>4}  {tag:>8}  {novel:<25}  "
                       + (f"0x{bits:02X} ({bits:08b})" if bits else "-"))
    if not out:
        out.append("No differences: every ID and byte value in the action capture also appears in the baseline.")
    return "\n".join(out)


# --------------------------------------------------------------------------- self-test

def _synthetic(path, with_action=False):
    crc = _crc8(0x1D, 0xFF, 0xFF)
    with open(path, "w") as fh:
        t = 1700000000.0
        for i in range(400):
            t += 0.01
            rpm = 3000 + i * 20                       # big-endian 16-bit ramp in bytes 0-1
            body = bytes([rpm >> 8, rpm & 0xFF, 0x00, 0x55, i & 0x0F, 0, 0])
            fh.write(f"({t:.6f}) can0 0C9#{(body + bytes([crc(body)])).hex().upper()}\n")
            door = 0x04 if with_action and 100 < i < 200 else 0x00
            fh.write(f"({t + 0.001:.6f}) can0 3B3#{bytes([0x40, door, 0, 0]).hex().upper()}\n")
            if i % 10 == 0:
                fh.write(f"({t + 0.002:.6f}) can0 18FEEE00#6E{'FF' * 7}\n")
            if with_action and i == 150:
                fh.write(f"({t + 0.003:.6f}) can0 7DF#02010C0000000000\n")


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        _self_test(d)
    print("self-test OK")


def _self_test(d):
    import os
    a, b = os.path.join(d, "base.log"), os.path.join(d, "act.log")
    _synthetic(a)
    _synthetic(b, with_action=True)
    base, act = group(read_frames(a)), group(read_frames(b))
    assert len(base) == 3 and len(base[(0x0C9, False)]) == 400
    tags, notes = classify(0x0C9, base[(0x0C9, False)])
    assert tags[2:5] == ["00", "55", "cn"] and tags[7] == "ck", tags
    assert any("J1850" in n for n in notes) and any("low nibble" in n for n in notes), notes
    med, _ = period_stats(base[(0x0C9, False)])
    assert abs(med - 10.0) < 0.01, med
    assert any("big-endian" in s and "0-1" in s for s in carry_pairs(base[(0x0C9, False)], 8))
    assert j1939_fields(0x0CF00400) == (3, 61444, None, 0)
    assert j1939_fields(0x18EAFF00) == (6, 59904, 0xFF, 0)
    assert j1939_fields(0x18FEEE00)[1] == 65262
    report = diff(base, act)
    assert "7DF" in report.splitlines()[0], report
    assert any(l.split()[:2] == ["3B3", "1"] and "0x04" in l for l in report.splitlines()), report
    assert "0C9" not in report.split("\n", 1)[1], report  # counter/CRC/ramp bytes must not show as changes
    # console-format and CSV parsing
    c = os.path.join(d, "console.txt")
    with open(c, "w") as fh:
        fh.write("  can0  123   [3]  DE AD BE\n (1.500000)  can0  18DAF110   [2]  01 02\n")
        fh.write("(1.6) can0 123##1AABB\n(1.7) can0 123#R\n(1.8) can0 20000004#0000000000000000\n")
        fh.write("7E8#03410580\n")
        # skipped: a console remote frame, and a console line cut off before its stated 8 bytes
        fh.write("  can0  123   [0]  remote request\n  can0  123   [8]  DE AD\n")
    fr = list(read_frames(c))
    assert [(f.can_id, f.ext, f.data.hex(), f.bus) for f in fr] == \
        [(0x123, False, "deadbe", "can0"), (0x18DAF110, True, "0102", "can0"), (0x123, False, "aabb", "can0"),
         (0x7E8, False, "03410580", "")], fr
    assert [f.timed for f in fr] == [False, True, True, False]
    assert period_stats([f for f in fr if not f.timed]) == (None, None)   # no invented period
    s = os.path.join(d, "savvy.csv")
    with open(s, "w") as fh:
        fh.write("Time Stamp,ID,Extended,Dir,Bus,LEN,D1,D2,D3,D4,D5,D6,D7,D8\n")
        fh.write("1000000,0000018F,false,Rx,0,2,AA,BB,,,,,,\n1000100,0000018F,false,Rx,1,2,AA,BB,,,,,,\n")
    assert list(read_frames(s))[0] == Frame(1.0, 0x18F, False, b"\xaa\xbb", "0")
    assert len(load(s, "1")) == 1
    for bad in (lambda: load(s), lambda: load(os.path.join(d, "missing.log"))):   # two buses; no such file
        try:
            bad()
            raise AssertionError("load() should have refused")
        except SystemExit as e:
            assert str(e.code).startswith("error:"), e.code


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", help="candump log, candump console output, or SavvyCAN CSV")
    ap.add_argument("--id", help="show per-byte and per-bit detail for one CAN ID (hex)")
    ap.add_argument("--diff", metavar="ACTION_LOG",
                    help="treat LOG as the baseline and report what is new in ACTION_LOG")
    ap.add_argument("--j1939", action="store_true", help="label 29-bit IDs with priority/PGN/SA")
    ap.add_argument("--min-count", type=int, default=1, help="hide IDs seen fewer than N times")
    ap.add_argument("--bus", help="interface name (can0) or CSV bus number to analyse, when the file holds several")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.log:
        ap.error("a log file is required")
    unrecognised = ("No CAN frames recognised in {}. Supported: candump -l/-L logs, candump console output, "
                    "ID#DATA lines, SavvyCAN/GVRET CSV. Convert others with python-can (`python -m can.logconvert`).")
    by_id = group(load(a.log, a.bus))
    if not by_id:
        print(unrecognised.format(a.log), file=sys.stderr)
        return 1
    if a.diff:
        act = group(load(a.diff, a.bus))
        if not act:   # otherwise every baseline ID would be reported as having disappeared
            print(unrecognised.format(a.diff), file=sys.stderr)
            return 1
        print(diff(by_id, act))
    elif a.id:
        try:
            text = detail(by_id, int(a.id, 16))
        except ValueError:
            ap.error(f"--id takes a hex CAN ID, got {a.id!r}")
        if text is None:
            print(f"error: ID {a.id} is not in {a.log}", file=sys.stderr)
            return 1
        print(text)
    else:
        print(summary(by_id, a.j1939, a.min_count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
