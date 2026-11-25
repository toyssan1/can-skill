#!/usr/bin/env python3
"""Find the CAN signal that tracks a known reference value.

Given a capture and a reference (a value over time that you can already decode),
this tries bit fields in every broadcast message (start bit, length, byte order,
sign), ranks them by how well they follow the reference, then fits scale and
offset and prints a DBC signal line.

The search is wide but not exhaustive. It skips fields whose end bits never
change, bits that belong to a counter or checksum, and frames carrying an
all-ones "not available" value. IDs are first ranked on fields of up to 16 bits
from a sample of frames, and only the best --top IDs get the full search. IDs
in 0x700-0x7FF and 18DAxxxx/18DBxxxx are left out as diagnostic traffic unless
you name them with --ids. Multiplexed messages are not handled.

What it prints is a candidate, however good the fit: a field fitted to a capture
always looks good on that capture. Only --check on a different capture says
CONFIRMED.

References, pick one:
  --obd-pid 0C            an OBD-II PID polled during the same capture (best: same clock)
  --ref-signal "0x18FEF100 8|16@1+ (0.00390625,0)"
                          a signal in the log you can already decode (J1939, GPS-to-CAN, a known DBC)
  --ref-csv ref.csv       two columns: time in seconds, value (phone GPS, dash logger, typed-in notes)

    can_signal_search.py drive.log                        # list the OBD-II PIDs available as references
    can_signal_search.py drive.log --obd-pid 0D           # find vehicle speed
    can_signal_search.py drive2.log --obd-pid 0D --check "0x1A0 4|12@1+ (0.1,0)"
                                                          # gate a result on a second capture
    can_signal_search.py --self-test

The reference must sweep a good part of its range during the capture: a signal
cannot be told apart from a constant if the reference never moves.

Standard library only. Python 3.8+. Needs can_log_analyze.py and obd_decode.py
from the same directory.
"""
import argparse
import bisect
import math
import os
import re
import statistics
import sys
from operator import mul

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_log_analyze import find_checksum, find_counter, fmt_id, group, load, read_frames  # noqa: E402
import obd_decode  # noqa: E402

COARSE_SAMPLES = 120     # per ID, to rank IDs quickly
FINE_SAMPLES = 600       # per ID, for the full field search
SATURATED = 0.35         # a bit toggling on this share of frames is at the noise floor
SPEC = re.compile(r"^\s*(?:0x)?([0-9A-Fa-f]+)\s+(\d+)\|(\d+)@([01])([+-])"
                  r"(?:\s*\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\))?\s*$")
COUNTER_BITS = {"byte": range(0, 8), "low nibble": range(0, 4), "high nibble": range(4, 8),
                "bits 7-6": range(6, 8), "bits 5-4": range(4, 6)}


# --------------------------------------------------------------------------- bit fields

def le_index(q):
    """Transmission-order bit position (0 = MSB of byte 0) -> DBC bit number (bit 0 = LSB of byte 0)."""
    return (q // 8) * 8 + 7 - q % 8


def field_bits(order, pos, length):
    """DBC bit numbers of a field, most significant first. For 'le' pos is the LSB; for 'be' pos is the
    transmission-order position of the MSB."""
    if order == "le":
        return list(range(pos + length - 1, pos - 1, -1))
    return [le_index(q) for q in range(pos, pos + length)]


def dbc_start(order, pos):
    return pos if order == "le" else le_index(pos)


def from_dbc(start, length, little):
    """DBC start bit -> (order, pos) as used internally."""
    if little:
        return "le", start
    byte, bit = divmod(start, 8)
    return "be", byte * 8 + (7 - bit)


def extract(vals, nbits, order, pos, length, signed=False):
    """Raw integer series. vals is the per-frame payload as an int in the matching byte order."""
    shift = pos if order == "le" else nbits - pos - length
    mask = (1 << length) - 1
    out = [(v >> shift) & mask for v in vals]
    if signed:
        half, full = 1 << (length - 1), 1 << length
        out = [x - full if x >= half else x for x in out]
    return out


# --------------------------------------------------------------------------- reference

def ref_from_obd(frames, pid):
    """(times, values, label) from single-frame Mode 01 responses in the capture."""
    if obd_decode.pid_value(pid, [0, 0, 0, 0, 0]) is None:
        raise SystemExit(f"PID {pid:02X} is not a plain numeric value; pick another reference.")
    per_ecu = {}
    for f in frames:
        d = f.data
        is_resp = (not f.ext and 0x7E8 <= f.can_id <= 0x7EF) or (f.ext and f.can_id >> 8 == 0x18DAF1)
        if is_resp and len(d) >= 4 and 2 <= d[0] <= 7 and d[1] == 0x41 and d[2] == pid:
            v = obd_decode.pid_value(pid, d[3:1 + d[0]])
            if v is not None:
                per_ecu.setdefault((f.can_id, f.ext), []).append((f.ts, v))
    if not per_ecu:
        raise SystemExit(f"No OBD-II responses for PID {pid:02X} in this capture. Run without options to list "
                         f"the PIDs it contains.")
    key = max(per_ecu, key=lambda k: len(per_ecu[k]))
    pts = per_ecu[key]
    name, unit = obd_decode.PIDS[pid][0], obd_decode.PIDS[pid][2].unit
    return [t for t, _ in pts], [v for _, v in pts], f"OBD-II PID {pid:02X} {name} from {fmt_id(*key)}", unit


def parse_spec(by_id, spec):
    """'ID start|len@order sign (scale,offset)' -> (key, prepared series, field, scale, offset).
    Exits with a message when the text does not parse, the ID is absent, or the field does not fit."""
    m = SPEC.match(spec)
    if not m:
        raise SystemExit(f'Cannot parse signal "{spec}". Expected e.g. "0x18FEF100 8|16@1+ (0.00390625,0)".')
    can_id, start, length = int(m.group(1), 16), int(m.group(2)), int(m.group(3))
    keys = [k for k in by_id if k[0] == can_id]
    if not keys:
        raise SystemExit(f"ID {can_id:X} is not in the capture.")
    s = prepare(by_id[keys[0]])
    order, pos = from_dbc(start, length, m.group(4) == "1")
    if length < 1 or start >= s["nbits"] or pos + length > s["nbits"]:
        raise SystemExit(f'"{spec.strip()}" does not fit: ID {can_id:X} carries {s["nbits"] // 8} data bytes '
                         f'(bits 0-{s["nbits"] - 1}), and this field runs past the end of the payload.')
    return keys[0], s, (order, pos, length, m.group(5) == "-"), float(m.group(6) or 1), float(m.group(7) or 0)


def ref_from_signal(by_id, spec):
    key, s, (order, pos, length, signed), scale, offset = parse_spec(by_id, spec)
    raw = extract(s["le"] if order == "le" else s["be"], s["nbits"], order, pos, length, signed)
    return s["ts"], [x * scale + offset for x in raw], f"signal {spec.strip()}", "", key


def ref_from_csv(path, t0, offset):
    ts, vs = [], []
    with open(path, errors="replace") as fh:
        for line in fh:
            parts = re.split(r"[,;\t ]+", line.strip())
            try:
                t, v = float(parts[0]), float(parts[1])   # both or neither: the two lists must stay in step
            except (ValueError, IndexError):
                continue                                  # header, blank line, or a row with a missing value
            ts.append(t)
            vs.append(v)
    if len(ts) < 5:
        raise SystemExit(f"{path}: need at least 5 rows of 'time,value'.")
    note = ""
    if max(ts) < 1e7 < t0:                                # relative seconds against an epoch-stamped log
        ts = [t + t0 for t in ts]
        note = " (times taken as seconds from the first frame of the log)"
    ts = [t + offset for t in ts]
    return ts, vs, f"{os.path.basename(path)}{note}", ""


def list_obd_refs(frames):
    seen = {}
    for f in frames:
        d = f.data
        if ((not f.ext and 0x7E8 <= f.can_id <= 0x7EF) or (f.ext and f.can_id >> 8 == 0x18DAF1)) \
                and len(d) >= 4 and 2 <= d[0] <= 7 and d[1] == 0x41:
            v = obd_decode.pid_value(d[2], d[3:1 + d[0]])
            if v is not None:
                seen.setdefault(d[2], []).append(v)
    return seen


class Reference:
    def __init__(self, ts, vs, label, unit=""):
        order = sorted(range(len(ts)), key=ts.__getitem__)
        self.t = [ts[i] for i in order]
        self.v = [vs[i] for i in order]
        self.label, self.unit = label, unit
        self.lo, self.hi = min(vs), max(vs)
        self.span = self.hi - self.lo
        gaps = sorted(b - a for a, b in zip(self.t, self.t[1:]))
        # tolerate gaps up to a few sample periods; beyond that the reference is unknown
        self.max_gap = max(2.0, 4 * gaps[len(gaps) // 2]) if gaps else 2.0

    def at(self, t):
        """Linear interpolation, or None outside the reference or inside a long gap."""
        i = bisect.bisect_right(self.t, t)
        if i == 0 or i == len(self.t):
            return None
        t0, t1 = self.t[i - 1], self.t[i]
        if t1 - t0 > self.max_gap:
            return None
        return self.v[i - 1] + (self.v[i] - self.v[i - 1]) * (t - t0) / (t1 - t0) if t1 > t0 else self.v[i]


# --------------------------------------------------------------------------- per-ID preparation

def prepare(frames):
    """Keep the dominant payload length, pre-compute both integer forms, bit activity and blocked bits."""
    lengths = {}
    for f in frames:
        lengths[len(f.data)] = lengths.get(len(f.data), 0) + 1
    n = max(lengths, key=lengths.get)
    fr = [f for f in frames if len(f.data) == n]
    # Frames that carry an all-ones "not available" value (two or more adjacent FF bytes that are FF only in
    # a small minority of frames) would wreck any fit, so they are set aside and counted.
    rare = [sum(1 for f in fr if f.data[b] == 0xFF) <= 0.15 * len(fr) for b in range(n)]
    marked = [f for f in fr if any(rare[b] and rare[b + 1] and f.data[b] == f.data[b + 1] == 0xFF
                                   for b in range(n - 1))]
    dropped = len(marked) if 0 < len(marked) <= 0.15 * len(fr) else 0
    if dropped:
        gone = set(map(id, marked))
        fr = [f for f in fr if id(f) not in gone]
    le = [int.from_bytes(f.data, "little") for f in fr]
    nbits = n * 8
    flips = [0] * nbits
    for a, b in zip(le, le[1:]):
        x = a ^ b
        while x:
            low = x & -x
            flips[low.bit_length() - 1] += 1
            x ^= low
    blocked = [False] * nbits                 # counters and checksums track nothing physical
    for byte in range(n):
        label = find_counter([f.data[byte] for f in fr])
        for b in COUNTER_BITS.get(label, ()):
            blocked[byte * 8 + b] = True
    ck = find_checksum(fr[0].can_id, [f.data for f in fr]) if fr else None
    if ck:
        for b in range(8):
            blocked[ck[0] * 8 + b] = True
    return dict(ts=[f.ts for f in fr], le=le, be=[int.from_bytes(f.data, "big") for f in fr], nbits=nbits,
                flips=flips, blocked=blocked, n=len(fr), dropped=dropped)


def aligned(series, ref, lag, limit):
    """Indices of frames that have a reference value, thinned to `limit`, with those reference values."""
    idx, ys = [], []
    for i, t in enumerate(series["ts"]):
        y = ref.at(t + lag)
        if y is not None:
            idx.append(i)
            ys.append(y)
    if len(idx) > limit:
        step = len(idx) / limit
        pick = [int(k * step) for k in range(limit)]
        idx, ys = [idx[k] for k in pick], [ys[k] for k in pick]
    return idx, ys


def candidates(s, min_len, max_len):
    """Every field whose two end bits both change. A field with a constant end bit is the same signal as a
    narrower one, so skipping those removes duplicates without losing anything."""
    nbits, flips, blocked = s["nbits"], s["flips"], s["blocked"]
    for pos in range(nbits):                                   # little-endian: pos = LSB
        if flips[pos] and not blocked[pos]:
            for length in range(min_len, max_len + 1):
                top = pos + length - 1
                if top >= nbits or blocked[top]:
                    break
                if flips[top]:
                    yield "le", pos, length
    for pos in range(nbits):                                   # big-endian: pos = MSB in transmission order
        if flips[le_index(pos)] and not blocked[le_index(pos)]:
            for length in range(max(min_len, 2), max_len + 1):
                last = pos + length - 1
                if last >= nbits or blocked[le_index(last)]:
                    break
                if last // 8 != pos // 8 and flips[le_index(last)]:    # inside one byte it equals 'le'
                    yield "be", pos, length


def r_value(xs, ys, sy, syy):
    n = len(xs)
    sx = sum(xs)
    vx = sum(map(mul, xs, xs)) - sx * sx / n
    vy = syy - sy * sy / n
    if vx <= 0 or vy <= 0:
        return 0.0
    return (sum(map(mul, xs, ys)) - sx * sy / n) / math.sqrt(vx * vy)


def search(s, ref, limit, min_len, max_len, lag=0.0):
    """Score every candidate field of one ID. Returns {(order, pos, length, signed): r}."""
    idx, ys = aligned(s, ref, lag, limit)
    if len(idx) < 20 or len(set(ys)) < 4:
        return {}
    sy, syy = sum(ys), sum(map(mul, ys, ys))
    le, be = [s["le"][i] for i in idx], [s["be"][i] for i in idx]
    out = {}
    for order, pos, length in candidates(s, min_len, max_len):
        xs = extract(le if order == "le" else be, s["nbits"], order, pos, length)
        out[(order, pos, length, False)] = r_value(xs, ys, sy, syy)
        half = 1 << (length - 1)
        if min(xs) < half <= max(xs):                          # sign only matters if the top bit is used
            full = 1 << length
            out[(order, pos, length, True)] = r_value([x - full if x >= half else x for x in xs], ys, sy, syy)
    return out


def settle_extent(s, scores):
    """Choose the field of record from the scored candidates of one ID.

    The best-correlating candidate fixes the byte order, sign and most significant bit. The low end is then
    decided on evidence, because extra low bits barely change a correlation: start from the shortest field
    that still fits, and take in each further low bit only if the fit improves or the bit continues the
    pattern of a real number (each lower bit toggles at least as often as the one above). Anything taken on
    weaker evidence is reported as an assumption.
    """
    best_key = max(scores, key=lambda k: scores[k] ** 2)
    order, pos, length, signed = best_key
    best = scores[best_key] ** 2
    msb = field_bits(order, pos, length)[0]
    same = {}                                                  # length -> r2, for fields sharing this MSB
    for (o, p, ln, sg), r in scores.items():
        if o == order and sg == signed and field_bits(o, p, ln)[0] == msb:
            same[ln] = r * r
    cur = min(ln for ln, r2 in same.items() if r2 >= best - 0.01)
    flips, n = s["flips"], max(s["n"] - 1, 1)

    def lsb(ln):
        p = pos + length - ln if order == "le" else pos
        return field_bits(order, p, ln)[-1]

    assumed = 0
    while cur + 1 in same and same[cur + 1] >= best - 0.01:
        f_cur, f_next = flips[lsb(cur)], flips[lsb(cur + 1)]
        improves = same[cur + 1] - same[cur] > 0.02 * (1 - same[cur]) + 1e-9
        saturated = f_cur / n >= SATURATED
        # At the noise floor every lower bit looks alike, so the toggle pattern alone is not allowed to carry
        # the field across a byte boundary: that is where an unrelated noisy byte (a checksum) would start.
        cascades = f_next >= 0.8 * f_cur and not (saturated and lsb(cur) % 8 == 0)
        if not (improves or cascades):
            break
        assumed = assumed + 1 if saturated and not improves else 0
        cur += 1
    notes = []
    p = pos + length - cur if order == "le" else pos
    if assumed:
        notes.append(f"the lowest {assumed} bit(s) toggle like noise; they are included because they continue "
                     f"the field's pattern, but this capture cannot prove they belong to it")
    # high end: constant-zero bits above may belong to the field (the value never got that large)
    bits = field_bits(order, p, cur)
    high, grow = bits[0], 0
    while (high + grow + 1) % 8 != 0 and not signed:
        b = high + grow + 1
        if flips[b] or s["blocked"][b] or any(v >> b & 1 for v in s["le"][:50]):
            grow = 0
            break
        grow += 1
    if grow and cur + grow <= 32:
        cur += grow
        p = p if order == "le" else p - grow
        notes.append(f"the top {grow} bit(s) stayed 0 in this capture; they are included on the assumption that "
                     f"the field is byte aligned")
    return order, p, cur, signed, notes


# --------------------------------------------------------------------------- calibration and checking

NEAT = sorted({m * 10.0 ** k for m in (1, 2, 2.5, 4, 5) for k in range(-7, 4)} | {2.0 ** -j for j in range(1, 17)})


def fit_line(xs, ys):
    """Robust line: median of pairwise slopes (resists outliers and lag), then the median intercept."""
    step = max(1, len(xs) // 200)
    px, py = xs[::step], ys[::step]
    slopes = [(py[j] - py[i]) / (px[j] - px[i]) for i in range(len(px)) for j in range(i + 1, len(px))
              if px[j] != px[i]]
    if not slopes:
        return 0.0, statistics.median(ys)
    k = statistics.median(slopes)
    return k, statistics.median(y - k * x for x, y in zip(xs, ys))


def neat_fit(xs, ys, k, c, span):
    """Snap to a round scale and offset if that moves the decode by under 1 % of the range."""
    if k == 0:
        return k, c, None
    mag = min(NEAT, key=lambda v: abs(math.log(v / abs(k))))
    k2 = math.copysign(mag, k)
    c2 = statistics.median(y - k2 * x for x, y in zip(xs, ys))
    c2 = 0.0 if abs(c2) < 0.005 * span else float(round(c2))
    bias = max(abs((k2 - k) * x + (c2 - c)) for x in xs) / span if span else 1.0
    return (k2, c2, bias) if bias <= 0.01 else (k, c, bias)


def evaluate(xs_phys, ys, span):
    """Agreement of a decoded series with the reference."""
    n = len(ys)
    r = r_value(xs_phys, ys, sum(ys), sum(map(mul, ys, ys)))
    err = [x - y for x, y in zip(xs_phys, ys)]
    mae = sum(map(abs, err)) / n
    slope, _ = fit_line(ys, xs_phys)
    steady, moving = [], []
    for i in range(1, n):
        (steady if abs(ys[i] - ys[i - 1]) <= 0.005 * span else moving).append(abs(err[i]))
    rest = [x for x, y in zip(xs_phys, ys) if y == 0]
    return dict(r2=r * r, mae=mae, bias=sum(err) / n, slope=slope,
                steady=sum(steady) / len(steady) if steady else None,
                moving=sum(moving) / len(moving) if moving else None,
                rest=statistics.median(rest) if len(rest) >= max(5, n // 30) else None)


def best_lag(s, ref, field, limit):
    order, pos, length, signed = field
    best = (0.0, -1.0)
    for step in range(-10, 11):
        lag = step / 10
        idx, ys = aligned(s, ref, lag, limit)
        if len(idx) < 20:
            continue
        vals = [s["le" if order == "le" else "be"][i] for i in idx]
        r = r_value(extract(vals, s["nbits"], order, pos, length, signed), ys, sum(ys), sum(map(mul, ys, ys)))
        if r * r > best[1] + (0.002 if lag else 0):            # prefer zero lag unless clearly better
            best = (lag, r * r)
    return best[0]


def decode_series(s, ref, field, lag, limit=FINE_SAMPLES):
    order, pos, length, signed = field
    idx, ys = aligned(s, ref, lag, limit)
    vals = [s["le" if order == "le" else "be"][i] for i in idx]
    return extract(vals, s["nbits"], order, pos, length, signed), ys


def fmt_num(v):
    return f"{v:.10g}"


def dbc_line(name, field, k, c, unit):
    order, pos, length, signed = field
    lo_raw, hi_raw = (-(1 << (length - 1)), (1 << (length - 1)) - 1) if signed else (0, (1 << length) - 1)
    lo, hi = sorted((lo_raw * k + c, hi_raw * k + c))          # the representable range, not the observed one
    return (f' SG_ {name} : {dbc_start(order, pos)}|{length}@{"1" if order == "le" else "0"}{"-" if signed else "+"} '
            f'({fmt_num(k)},{fmt_num(c)}) [{fmt_num(lo)}|{fmt_num(hi)}] "{unit}" Vector__XXX')


def spec_text(key, field, k, c):
    order, pos, length, signed = field
    return (f'0x{fmt_id(*key)} {dbc_start(order, pos)}|{length}@{"1" if order == "le" else "0"}'
            f'{"-" if signed else "+"} ({fmt_num(k)},{fmt_num(c)})')


def agreement_lines(ev, ref):
    span, u = ref.span, ref.unit
    out = [f"    fit: r2 {ev['r2']:.4f}, mean abs error {ev['mae']:.3g} {u} ({100 * ev['mae'] / span:.1f} % of range), "
           f"bias {ev['bias']:+.3g}, slope {ev['slope']:.3f}"]
    if ev["steady"] is not None and ev["moving"] is not None:
        out.append(f"    error while steady {ev['steady']:.3g}, while changing {ev['moving']:.3g}")
        if ev["moving"] > max(3 * ev["steady"], 0.03 * span):
            out.append("    WARNING: agrees when steady but not while changing. That is the signature of a wrong "
                       "field (or a large time offset between reference and bus).")
    if ev["rest"] is not None:
        out.append(f"    reads {ev['rest']:.3g} {u} when the reference is 0"
                   + ("   WARNING: should be 0" if abs(ev["rest"]) > 0.01 * span else ""))
    return out


# A search result is graded on the capture it was fitted to, so it is never called confirmed.
CANDIDATE = {"CONFIRMED": "STRONG CANDIDATE", "PLAUSIBLE": "WEAK CANDIDATE", "UNCONFIRMED": "POOR FIT"}


def verdict(ev, span):
    if ev["r2"] >= 0.98 and ev["mae"] <= 0.03 * span and abs(ev["bias"]) <= 0.02 * span and 0.97 <= ev["slope"] <= 1.03:
        return "CONFIRMED"
    return "PLAUSIBLE" if ev["r2"] >= 0.90 else "UNCONFIRMED"


# --------------------------------------------------------------------------- top level

def run_search(by_id, ref, exclude, top, min_len, max_len, min_frames=40, out=print):
    series, coarse = {}, {}
    for key, frames in by_id.items():
        if key in exclude or len(frames) < min_frames:
            continue
        s = prepare(frames)
        scores = search(s, ref, COARSE_SAMPLES, min_len, min(max_len, max(16, min_len)))
        if scores:
            series[key] = s
            coarse[key] = max(r * r for r in scores.values())
    if not coarse:
        out("No broadcast message overlaps the reference in time, or the reference never changes.")
        return []
    ranked = sorted(coarse, key=coarse.get, reverse=True)
    out(f"Searched {len(coarse)} IDs. Best coarse fit per ID: "
        + ", ".join(f"{fmt_id(*k)} {coarse[k]:.2f}" for k in ranked[:8]))
    results = []
    for key in ranked[:top]:
        s = series[key]
        scores = search(s, ref, FINE_SAMPLES, min_len, max_len)
        if not scores:
            continue
        order, pos, length, signed, notes = settle_extent(s, scores)
        field = (order, pos, length, signed)
        lag = best_lag(s, ref, field, FINE_SAMPLES)
        xs, ys = decode_series(s, ref, field, lag)
        k, c = fit_line(xs, ys)
        k2, c2, snap = neat_fit(xs, ys, k, c, ref.span)
        ev = evaluate([x * k2 + c2 for x in xs], ys, ref.span)
        if s["dropped"]:
            notes.append(f"{s['dropped']} frame(s) carrying an all-ones 'not available' value were left out")
        results.append(dict(key=key, field=field, lag=lag, fit=(k, c), cal=(k2, c2), snap=snap, ev=ev, notes=notes))
    results.sort(key=lambda r: r["ev"]["r2"], reverse=True)
    for rank, r in enumerate(results, 1):
        k, c = r["fit"]
        k2, c2 = r["cal"]
        order = "little-endian" if r["field"][0] == "le" else "big-endian"
        out(f"\n#{rank}  ID {fmt_id(*r['key'])}  {order}, {'signed' if r['field'][3] else 'unsigned'}, "
            f"{r['field'][2]} bits   [{CANDIDATE[verdict(r['ev'], ref.span)]}]")
        out("   " + dbc_line("Signal", r["field"], k2, c2, ref.unit))
        if (k2, c2) != (k, c):
            out(f"    scale and offset rounded from the fitted {fmt_num(k)}, {fmt_num(c)} "
                f"(moves the decode by {100 * r['snap']:.2f} % of range)")
        elif r["snap"] is not None:
            out(f"    fitted scale is not a round number (nearest round value would shift the decode by "
                f"{100 * r['snap']:.1f} % of range): treat the field with suspicion")
        for line in agreement_lines(r["ev"], ref):
            out(line)
        if r["lag"]:
            out(f"    reference lags the bus by {r['lag']:+.1f} s")
        for n in r["notes"]:
            out(f"    note: {n}")
    if results:
        best = results[0]
        out("\nThese are candidates: each was fitted to this capture, so a good fit here proves little. Several "
            "IDs can carry the same quantity (per-wheel speeds, a cluster copy): choose by update rate and "
            "resolution.\nNext: confirm on a different capture with\n  --check \""
            + spec_text(best["key"], best["field"], *best["cal"]) + '"')
    return results


def run_check(by_id, ref, spec, out=print):
    _key, s, field, k, c = parse_spec(by_id, spec)
    lag = best_lag(s, ref, field, FINE_SAMPLES)
    xs, ys = decode_series(s, ref, field, lag)
    if len(xs) < 20:
        raise SystemExit("Too little overlap between this ID and the reference.")
    ev = evaluate([x * k + c for x in xs], ys, ref.span)
    v = verdict(ev, ref.span)
    out(f"Check of {spec.strip()} against {ref.label}: {v}")
    for line in agreement_lines(ev, ref):
        out(line)
    if lag:
        out(f"    reference lags the bus by {lag:+.1f} s")
    if s["dropped"]:
        out(f"    note: {s['dropped']} frame(s) carrying an all-ones 'not available' value were left out")
    if v != "CONFIRMED":
        out("    Not confirmed. Do not explain this away as a noisy reference: for the right field the decode "
            "agrees both steady and changing. Re-run the search, or capture with a wider sweep.")
    return v


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        _self_test(d)
    print("self-test OK")


def _self_test(d):
    import random
    random.seed(3)
    crc = lambda b: sum(b) & 0xFF                              # noqa: E731

    def make(path, seed, speed_peak):
        rnd = random.Random(seed)
        lines, t = [], 1730000000.0
        for i in range(4000):                                  # 40 s, 10 ms ticks
            t += 0.01
            phase = i / 4000
            rpm = 900 + 2600 * abs(math.sin(phase * 9)) + rnd.gauss(0, 5)
            speed = max(0.0, speed_peak * math.sin(phase * math.pi) ** 2 * (1 if i > 400 else 0) + rnd.gauss(0, 0.05))
            raw = int(rpm * 4)
            body = bytes([raw >> 8, raw & 0xFF, 0x00, i & 0x0F, 0x10, 0, 0])
            lines.append((t, f"0C9#{(body + bytes([crc(body)])).hex()}"))
            if i % 2 == 0:
                sp = int(speed * 10) & 0xFFF                   # 12 bits at bit 4, little-endian, 0.1 km/h
                word = (sp << 4) | (0x1 if i % 700 < 30 else 0)
                if i < 80:
                    word = 0xFFFF                              # "not available" while the module starts up
                # the same quantity at a coarser resolution in another message, and unrelated wandering data
                lines.append((t + 0.001, f"1A0#{word.to_bytes(2, 'little').hex()}{rnd.randrange(256):02x}00"))
                lines.append((t + 0.002, f"2F1#{int(speed) & 0xFF:02x}{rnd.randrange(256):02x}{rnd.randrange(256):02x}"))
                temp = int(85 + 3 * math.sin(i / 300) + 40)
                lines.append((t + 0.003, f"3C0#{temp:02x}{(i // 2) & 0xFF:02x}0000"))
            if i % 10 == 0:                                    # OBD-II polling: rpm and speed alternately
                if (i // 10) % 2 == 0:
                    lines.append((t + 0.004, "7DF#02010C0000000000"))
                    lines.append((t + 0.006, f"7E8#04410C{int(rpm * 4):04x}000000"))
                else:
                    lines.append((t + 0.004, "7DF#02010D0000000000"))
                    lines.append((t + 0.006, f"7E8#03410D{int(speed) & 0xFF:02x}00000000"))
        with open(path, "w") as fh:
            for ts, text in sorted(lines):
                fh.write(f"({ts:.6f}) can0 {text}\n")

    a, b = os.path.join(d, "a.log"), os.path.join(d, "b.log")
    make(a, 1, 120)
    make(b, 2, 90)
    frames = list(read_frames(a))
    by_id = group(frames)
    exclude = {k for k in by_id if not k[1] and 0x700 <= k[0] <= 0x7FF}
    assert set(list_obd_refs(frames)) == {0x0C, 0x0D}
    quiet = lambda *_: None                                    # noqa: E731

    ref = Reference(*ref_from_obd(frames, 0x0C))
    res = run_search(by_id, ref, exclude, 3, 3, 24, out=quiet)
    top = res[0]
    assert top["key"] == (0x0C9, False) and top["field"] == ("be", 0, 16, False), top
    assert top["cal"] == (0.25, 0.0) and verdict(top["ev"], ref.span) == "CONFIRMED", top
    assert "7|16@0+ (0.25,0)" in dbc_line("x", top["field"], *top["cal"], "rpm")

    ref = Reference(*ref_from_obd(frames, 0x0D))
    res = run_search(by_id, ref, exclude, 3, 3, 24, out=quiet)
    top = res[0]
    assert top["key"] == (0x1A0, False) and top["field"] == ("le", 4, 12, False), top
    assert top["cal"] == (0.1, 0.0), top
    assert any("not available" in n for n in top["notes"]), top["notes"]
    assert any(r["key"] == (0x2F1, False) for r in res), res   # the coarse copy is reported too
    # gate on the second capture: the right field passes, a shifted or mis-scaled one does not
    frames2 = list(read_frames(b))
    by2 = group(frames2)
    ref2 = Reference(*ref_from_obd(frames2, 0x0D))
    assert run_check(by2, ref2, "0x1A0 4|12@1+ (0.1,0)", out=quiet) == "CONFIRMED"
    assert run_check(by2, ref2, "0x1A0 0|12@1+ (0.1,0)", out=quiet) != "CONFIRMED"
    assert run_check(by2, ref2, "0x1A0 4|12@1+ (0.11,0)", out=quiet) != "CONFIRMED"
    # a signal already decodable in the log works as a reference, and its own ID is excluded by the caller
    ts, vs, label, unit, key = ref_from_signal(by_id, "0x1A0 4|12@1+ (0.1,0)")
    res = run_search(by_id, Reference(ts, vs, label, unit), exclude | {key}, 2, 3, 24, out=quiet)
    assert res[0]["key"] == (0x2F1, False) and res[0]["field"][:3] == ("le", 0, 8), res[0]
    # an external reference file with times relative to the start of the log
    csv = os.path.join(d, "ref.csv")
    with open(csv, "w") as fh:
        fh.write("time_s,speed_kmh\n")
        fh.writelines(f"{t - frames[0].ts:.3f},{v}\n" for t, v in zip(ref.t, ref.v))
    cref = Reference(*ref_from_csv(csv, frames[0].ts, 0.0))
    assert "seconds from the first frame" in cref.label
    found = {r["key"][0]: r["field"] for r in run_search(by_id, cref, exclude, 2, 3, 24, out=quiet)}
    assert found[0x1A0] == ("le", 4, 12, False), found
    assert from_dbc(7, 16, False) == ("be", 0) and dbc_start("be", 0) == 7 and dbc_start("be", 12) == 11
    assert extract([0x0BB8405A05000099], 64, "be", 0, 16) == [0x0BB8]
    # a field that runs off the end of the payload is refused, not crashed on (0x1A0 has 4 bytes)
    for spec in ("0x1A0 27|12@0+ (0.1,0)", "0x1A0 28|8@1+", "0x1A0 40|4@1+"):
        try:
            run_check(by2, ref2, spec, out=quiet)
            raise AssertionError(f"{spec} should be refused")
        except SystemExit as e:
            assert "does not fit" in str(e.code), e.code
    # a minimum length above 16 still finds the 16-bit-plus fields (the coarse pass used to stop at 16)
    assert run_search(by_id, Reference(*ref_from_obd(frames, 0x0C)), exclude, 2, 17, 24, out=quiet)
    # a CSV row with a time but no value is skipped whole
    with open(csv, "a") as fh:
        fh.write("99999,\n")
    t, v, _, _ = ref_from_csv(csv, frames[0].ts, 0.0)
    assert len(t) == len(v) == len(ref.t)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", help="candump log, candump console output, ID#DATA lines, or SavvyCAN CSV")
    ap.add_argument("--obd-pid", help="hex Mode 01 PID polled in the same capture, e.g. 0C (rpm), 0D (speed)")
    ap.add_argument("--ref-signal", help='a decodable signal in the log: "ID start|len@order sign (scale,offset)"')
    ap.add_argument("--ref-csv", help="CSV of time (s), value")
    ap.add_argument("--ref-time-offset", type=float, default=0.0, help="seconds added to --ref-csv times")
    ap.add_argument("--check", metavar="SIGNAL", help="score one signal definition instead of searching")
    ap.add_argument("--ids", help="only search these hex IDs (comma separated). Also how to search IDs in "
                                  "0x700-0x7FF, which are otherwise skipped as diagnostic traffic")
    ap.add_argument("--bus", help="interface name (can0) or CSV bus number to use, when the file holds several")
    ap.add_argument("--exclude", help="hex IDs to leave out (comma separated)")
    ap.add_argument("--top", type=int, default=4, help="how many IDs to analyse in full (default 4)")
    ap.add_argument("--min-len", type=int, default=3)
    ap.add_argument("--max-len", type=int, default=24, help="longest field tried (default 24; use 32 if needed)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.log:
        ap.error("a log file is required")
    try:
        pid = int(a.obd_pid, 16) if a.obd_pid else None
        want = {int(x, 16) for x in a.ids.split(",")} if a.ids else None
        drop = {int(x, 16) for x in a.exclude.split(",")} if a.exclude else set()
    except ValueError:
        ap.error("--obd-pid, --ids and --exclude take hex numbers")
    frames = load(a.log, a.bus)
    if not frames:
        print("No CAN frames recognised in the log.", file=sys.stderr)
        return 1
    if not frames[0].timed:
        if a.ref_csv:
            print("error: the log has no timestamps, so it cannot be lined up with a CSV reference.", file=sys.stderr)
            return 1
        print("note: the log has no timestamps; frames are matched to the reference by their order in the file")
    by_id = group(frames)
    # Diagnostic traffic is skipped by default. The IDs the reference was read from are never searched.
    diag = {k for k in by_id if (not k[1] and 0x700 <= k[0] <= 0x7FF) or (k[1] and k[0] >> 16 in (0x18DA, 0x18DB))}
    ref_keys = set()
    if a.obd_pid:
        ref = Reference(*ref_from_obd(frames, pid))
        ref_keys = {k for k in diag if k[1] or 0x7DF <= k[0] <= 0x7EF}
    elif a.ref_signal:
        ts, vs, label, unit, key = ref_from_signal(by_id, a.ref_signal)
        ref = Reference(ts, vs, label, unit)
        ref_keys = {key}
    elif a.ref_csv:
        try:
            ref = Reference(*ref_from_csv(a.ref_csv, frames[0].ts, a.ref_time_offset))
        except OSError as e:
            print(f"error: cannot read {a.ref_csv}: {e.strerror}", file=sys.stderr)
            return 1
    else:
        refs = list_obd_refs(frames)
        if not refs:
            print("No OBD-II responses in this capture, so there is no built-in reference. Supply --ref-signal "
                  "or --ref-csv, or poll OBD-II PIDs while capturing (see references/reverse-engineering.md).")
            return 1
        print("OBD-II PIDs in this capture that can serve as a reference (--obd-pid XX):")
        for pid, vals in sorted(refs.items()):
            moved = "" if len(set(vals)) >= 4 else "   (barely changes: not usable)"
            print(f"  {pid:02X}  {obd_decode.PIDS[pid][0]:<40} {len(vals):>5} samples, "
                  f"{min(vals):g} .. {max(vals):g} {obd_decode.PIDS[pid][2].unit}{moved}")
        return 0
    if ref.span <= 0 or len(set(ref.v)) < 4:
        print(f"The reference ({ref.label}) takes fewer than 4 distinct values. Capture while it sweeps its range.")
        return 1
    print(f"Reference: {ref.label}, {len(ref.t)} samples, {ref.lo:g} .. {ref.hi:g} {ref.unit}")
    if a.check:
        return 0 if run_check(by_id, ref, a.check) == "CONFIRMED" else 3
    if want is not None:      # named IDs are searched even inside the diagnostic range (CANopen lives there)
        exclude = {k for k in by_id if k[0] not in want} | ref_keys
    else:
        exclude = diag | ref_keys
        skipped = sorted(diag - ref_keys)
        if skipped:
            print(f"Not searched (diagnostic ID range): {', '.join(fmt_id(*k) for k in skipped[:8])}"
                  f"{' ...' if len(skipped) > 8 else ''}. Name them with --ids if they are not diagnostic traffic.")
    exclude |= {k for k in by_id if k[0] in drop}
    return 0 if run_search(by_id, ref, exclude, a.top, a.min_len, a.max_len) else 1


if __name__ == "__main__":
    sys.exit(main())
