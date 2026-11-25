#!/usr/bin/env python3
"""OBD-II (SAE J1979 / ISO 15031-5) request and response decoder.

Give it the diagnostic payload: the bytes after the ISO-TP length/PCI byte,
starting with the service byte. Spaces are optional.

    obd_decode.py 41 0C 1A F8            -> Engine speed 1726 rpm
    obd_decode.py 4100BE1FA813           -> supported PID list
    obd_decode.py 43 02 01 33 C1 00      -> P0133, U0100
    obd_decode.py 49 02 01 31 47 31 ...  -> VIN
    obd_decode.py 7F 01 12               -> negative response
    obd_decode.py --legacy 43 01 33 00 00 00 00
                                         -> DTCs from a K-line / J1850 reply (no count byte)
    obd_decode.py --dtc P0133            -> DTC text <-> bytes, either direction
    obd_decode.py --pids                 -> the built-in Mode 01 PID table
    obd_decode.py --self-test

For raw CAN frames (7E8#04410C1AF8...) or multi-frame responses, run
isotp_decode.py on the log instead; it reassembles and then calls this decoder.

A payload that is too short for what it claims to carry is reported on a line
containing MALFORMED and the exit status is 1: nothing is guessed from a
partial reply. Exit status 2 means the input was not hex.

Standard library only. Python 3.8+.
"""
import argparse
import sys

SERVICES = {
    0x01: "Show current data", 0x02: "Show freeze frame data", 0x03: "Show stored DTCs",
    0x04: "Clear DTCs and stored values", 0x05: "O2 sensor monitoring test results (non-CAN)",
    0x06: "On-board monitoring test results", 0x07: "Show pending DTCs",
    0x08: "Control on-board system, test or component", 0x09: "Request vehicle information",
    0x0A: "Show permanent DTCs",
}

NRC = {
    0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported (or PID not supported)",
    0x13: "incorrectMessageLengthOrInvalidFormat", 0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect", 0x31: "requestOutOfRange", 0x33: "securityAccessDenied",
    0x78: "requestCorrectlyReceived-ResponsePending",
}


def u16(d, i=0):
    return (d[i] << 8) | d[i + 1]


def s16(d, i=0):
    v = u16(d, i)
    return v - 65536 if v & 0x8000 else v


def pct(a):
    return a * 100 / 255


def trim(a):
    return (a - 128) * 100 / 128


FUEL_SYSTEM = {0: "not present", 1: "open loop (engine not warm enough)", 2: "closed loop (O2 feedback)",
               4: "open loop (load or decel fuel cut)", 8: "open loop (system failure)",
               16: "closed loop with a feedback fault"}
OBD_STD = {1: "OBD-II (CARB)", 2: "OBD (EPA)", 3: "OBD and OBD-II", 4: "OBD-I", 5: "Not OBD compliant",
           6: "EOBD", 7: "EOBD and OBD-II", 8: "EOBD and OBD", 9: "EOBD, OBD and OBD-II", 10: "JOBD",
           11: "JOBD and OBD-II", 12: "JOBD and EOBD", 13: "JOBD, EOBD and OBD-II", 17: "EMD", 18: "EMD+",
           19: "HD OBD-C", 20: "HD OBD", 21: "WWH OBD", 23: "HD EOBD-I", 24: "HD EOBD-I N",
           25: "HD EOBD-II", 26: "HD EOBD-II N", 28: "OBDBr-1", 29: "OBDBr-2", 30: "KOBD",
           31: "IOBD I", 32: "IOBD II", 33: "HD EOBD-IV"}
FUEL_TYPE = {0: "not available", 1: "Gasoline", 2: "Methanol", 3: "Ethanol", 4: "Diesel", 5: "LPG", 6: "CNG",
             7: "Propane", 8: "Electric", 9: "Bifuel running gasoline", 10: "Bifuel running methanol",
             11: "Bifuel running ethanol", 12: "Bifuel running LPG", 13: "Bifuel running CNG",
             14: "Bifuel running propane", 15: "Bifuel running electricity",
             16: "Bifuel running electric and combustion", 17: "Hybrid gasoline", 18: "Hybrid ethanol",
             19: "Hybrid diesel", 20: "Hybrid electric", 21: "Hybrid electric and combustion",
             22: "Hybrid regenerative", 23: "Bifuel running diesel"}

SPARK_MONITORS = ["Catalyst", "Heated catalyst", "Evaporative system", "Secondary air system",
                  "A/C refrigerant", "Oxygen sensor", "Oxygen sensor heater", "EGR/VVT system"]
DIESEL_MONITORS = ["NMHC catalyst", "NOx/SCR aftertreatment", "(reserved)", "Boost pressure",
                   "(reserved)", "Exhaust gas sensor", "PM filter", "EGR/VVT system"]


def monitor_status(d, with_mil=True):
    """PID 01 (since codes were cleared) and PID 41 (this drive cycle) share one layout: a flag per monitor
    and a not-complete bit per monitor. The flag means "supported" in PID 01 and "enabled for this drive
    cycle" in PID 41, so the two are worded differently and PID 41 also lists what is not enabled."""
    a, b, c, e = d[0], d[1], d[2], d[3]
    out = []
    if with_mil:
        out.append(f"MIL {'ON' if a & 0x80 else 'off'}, {a & 0x7F} confirmed emissions DTC(s)")
    diesel = bool(b & 0x08)
    out.append("ignition type: " + ("compression (diesel)" if diesel else "spark"))
    names = ["Misfire", "Fuel system", "Comprehensive components"] + (DIESEL_MONITORS if diesel else SPARK_MONITORS)
    flag, not_done = (b & 7) | (c << 3), ((b >> 4) & 7) | (e << 3)
    pick = lambda want_flag, want_nd: ", ".join(                                   # noqa: E731
        n for i, n in enumerate(names)
        if n != "(reserved)" and bool(flag >> i & 1) == want_flag and bool(not_done >> i & 1) == want_nd) or "none"
    if with_mil:
        out.append("monitors complete: " + pick(True, False))
        out.append("monitors NOT complete: " + pick(True, True))
    else:
        out.append("enabled this drive cycle and complete: " + pick(True, False))
        out.append("enabled this drive cycle, NOT complete: " + pick(True, True))
        off = [x for x in (pick(False, False), pick(False, True)) if x != "none"]
        out.append("not enabled this drive cycle (or not fitted): " + (", ".join(off) or "none"))
    return "; ".join(out)


def o2_narrow(d):
    return f"{d[0] / 200:.3f} V" + ("" if d[1] == 0xFF else f", short-term trim {trim(d[1]):+.1f} %")


def o2_wide_v(d):
    return f"lambda {u16(d) * 2 / 65536:.3f}, {u16(d, 2) * 8 / 65536:.3f} V"


def o2_wide_ma(d):
    return f"lambda {u16(d) * 2 / 65536:.3f}, {u16(d, 2) / 256 - 128:+.2f} mA"


def o2_trims(d):
    """PIDs 55-58: one byte per bank. A reply may carry only the first bank's byte."""
    return ", ".join(f"{trim(x):+.1f} %" for x in d[:2])


def fuel_system(d):
    return "; ".join(f"system {i + 1}: {FUEL_SYSTEM.get(v, f'0x{v:02X}')}" for i, v in enumerate(d[:2]) if v or i == 0)


def num(fn, unit, fmt="{:.1f}"):
    def show(d):
        return (fmt.format(fn(d)) + " " + unit).strip()
    show.value, show.unit = fn, unit   # numeric access for other tools (can_signal_search.py)
    return show


def pid_value(pid, data):
    """Numeric value of a Mode 01 PID from its data bytes, or None if the PID is not a plain number."""
    entry = PIDS.get(pid)
    fn = getattr(entry[2], "value", None) if entry else None
    return None if fn is None or len(data) < entry[1] else float(fn(list(data)))


# pid: (name, data_bytes, formatter(data) -> str). A, B, C, D in the usual tables are d[0]..d[3].
PIDS = {
    0x01: ("Monitor status since DTCs cleared", 4, monitor_status),
    0x02: ("DTC that stored the freeze frame", 2, lambda d: dtc_text(d[0], d[1]) if u16(d) else "none"),
    0x03: ("Fuel system status", 2, fuel_system),
    0x04: ("Calculated engine load", 1, num(lambda d: pct(d[0]), "%")),
    0x05: ("Engine coolant temperature", 1, num(lambda d: d[0] - 40, "degC", "{:d}")),
    0x06: ("Short-term fuel trim, bank 1", 1, num(lambda d: trim(d[0]), "%", "{:+.1f}")),
    0x07: ("Long-term fuel trim, bank 1", 1, num(lambda d: trim(d[0]), "%", "{:+.1f}")),
    0x08: ("Short-term fuel trim, bank 2", 1, num(lambda d: trim(d[0]), "%", "{:+.1f}")),
    0x09: ("Long-term fuel trim, bank 2", 1, num(lambda d: trim(d[0]), "%", "{:+.1f}")),
    0x0A: ("Fuel pressure (gauge)", 1, num(lambda d: d[0] * 3, "kPa", "{:d}")),
    0x0B: ("Intake manifold absolute pressure", 1, num(lambda d: d[0], "kPa", "{:d}")),
    0x0C: ("Engine speed", 2, num(lambda d: u16(d) / 4, "rpm", "{:.2f}")),
    0x0D: ("Vehicle speed", 1, num(lambda d: d[0], "km/h", "{:d}")),
    0x0E: ("Timing advance", 1, num(lambda d: d[0] / 2 - 64, "deg before TDC")),
    0x0F: ("Intake air temperature", 1, num(lambda d: d[0] - 40, "degC", "{:d}")),
    0x10: ("Mass air flow rate", 2, num(lambda d: u16(d) / 100, "g/s", "{:.2f}")),
    0x11: ("Throttle position", 1, num(lambda d: pct(d[0]), "%")),
    0x12: ("Commanded secondary air status", 1, lambda d: f"0x{d[0]:02X} (bit-encoded)"),
    0x13: ("Oxygen sensors present (2 banks)", 1, lambda d: f"{d[0]:08b} (bits 0-3 bank 1 sensors 1-4, bits 4-7 bank 2)"),
    0x1C: ("OBD standard this vehicle conforms to", 1, lambda d: OBD_STD.get(d[0], f"value {d[0]}")),
    0x1D: ("Oxygen sensors present (4 banks)", 1, lambda d: f"{d[0]:08b}"),
    0x1E: ("Auxiliary input status", 1, lambda d: "PTO active" if d[0] & 1 else "PTO inactive"),
    0x1F: ("Run time since engine start", 2, num(u16, "s", "{:d}")),
    0x21: ("Distance travelled with MIL on", 2, num(u16, "km", "{:d}")),
    0x22: ("Fuel rail pressure (relative to manifold vacuum)", 2, num(lambda d: u16(d) * 0.079, "kPa", "{:.2f}")),
    0x23: ("Fuel rail gauge pressure (diesel / GDI)", 2, num(lambda d: u16(d) * 10, "kPa", "{:d}")),
    0x2C: ("Commanded EGR", 1, num(lambda d: pct(d[0]), "%")),
    0x2D: ("EGR error", 1, num(lambda d: trim(d[0]), "%", "{:+.1f}")),
    0x2E: ("Commanded evaporative purge", 1, num(lambda d: pct(d[0]), "%")),
    0x2F: ("Fuel tank level", 1, num(lambda d: pct(d[0]), "%")),
    0x30: ("Warm-ups since codes cleared", 1, num(lambda d: d[0], "", "{:d}")),
    0x31: ("Distance travelled since codes cleared", 2, num(u16, "km", "{:d}")),
    0x32: ("Evap system vapor pressure", 2, num(lambda d: s16(d) / 4, "Pa", "{:.2f}")),
    0x33: ("Absolute barometric pressure", 1, num(lambda d: d[0], "kPa", "{:d}")),
    0x3C: ("Catalyst temperature, bank 1 sensor 1", 2, num(lambda d: u16(d) / 10 - 40, "degC")),
    0x3D: ("Catalyst temperature, bank 2 sensor 1", 2, num(lambda d: u16(d) / 10 - 40, "degC")),
    0x3E: ("Catalyst temperature, bank 1 sensor 2", 2, num(lambda d: u16(d) / 10 - 40, "degC")),
    0x3F: ("Catalyst temperature, bank 2 sensor 2", 2, num(lambda d: u16(d) / 10 - 40, "degC")),
    0x41: ("Monitor status this drive cycle", 4, lambda d: monitor_status(d, with_mil=False)),
    0x42: ("Control module voltage", 2, num(lambda d: u16(d) / 1000, "V", "{:.3f}")),
    0x43: ("Absolute load value", 2, num(lambda d: u16(d) * 100 / 255, "%")),
    0x44: ("Commanded air-fuel equivalence ratio (lambda)", 2, num(lambda d: u16(d) * 2 / 65536, "", "{:.3f}")),
    0x45: ("Relative throttle position", 1, num(lambda d: pct(d[0]), "%")),
    0x46: ("Ambient air temperature", 1, num(lambda d: d[0] - 40, "degC", "{:d}")),
    0x47: ("Absolute throttle position B", 1, num(lambda d: pct(d[0]), "%")),
    0x48: ("Absolute throttle position C", 1, num(lambda d: pct(d[0]), "%")),
    0x49: ("Accelerator pedal position D", 1, num(lambda d: pct(d[0]), "%")),
    0x4A: ("Accelerator pedal position E", 1, num(lambda d: pct(d[0]), "%")),
    0x4B: ("Accelerator pedal position F", 1, num(lambda d: pct(d[0]), "%")),
    0x4C: ("Commanded throttle actuator", 1, num(lambda d: pct(d[0]), "%")),
    0x4D: ("Time run with MIL on", 2, num(u16, "min", "{:d}")),
    0x4E: ("Time since trouble codes cleared", 2, num(u16, "min", "{:d}")),
    0x4F: ("Maximum values: lambda, O2 voltage, O2 current, MAP", 4,
           lambda d: f"lambda {d[0]}, {d[1]} V, {d[2]} mA, {d[3] * 10} kPa"),
    0x50: ("Maximum air flow rate from MAF sensor", 4, num(lambda d: d[0] * 10, "g/s", "{:d}")),
    0x51: ("Fuel type", 1, lambda d: FUEL_TYPE.get(d[0], f"value {d[0]}")),
    0x52: ("Ethanol fuel percentage", 1, num(lambda d: pct(d[0]), "%")),
    0x53: ("Absolute evap system vapor pressure", 2, num(lambda d: u16(d) / 200, "kPa", "{:.3f}")),
    0x54: ("Evap system vapor pressure", 2, num(s16, "Pa", "{:d}")),
    0x55: ("Short-term secondary O2 trim, banks 1 and 3", 2, o2_trims),
    0x56: ("Long-term secondary O2 trim, banks 1 and 3", 2, o2_trims),
    0x57: ("Short-term secondary O2 trim, banks 2 and 4", 2, o2_trims),
    0x58: ("Long-term secondary O2 trim, banks 2 and 4", 2, o2_trims),
    0x59: ("Fuel rail absolute pressure", 2, num(lambda d: u16(d) * 10, "kPa", "{:d}")),
    0x5A: ("Relative accelerator pedal position", 1, num(lambda d: pct(d[0]), "%")),
    0x5B: ("Hybrid battery pack remaining life", 1, num(lambda d: pct(d[0]), "%")),
    0x5C: ("Engine oil temperature", 1, num(lambda d: d[0] - 40, "degC", "{:d}")),
    0x5D: ("Fuel injection timing", 2, num(lambda d: u16(d) / 128 - 210, "deg", "{:.2f}")),
    0x5E: ("Engine fuel rate", 2, num(lambda d: u16(d) / 20, "L/h", "{:.2f}")),
    0x5F: ("Emission requirements this vehicle is designed for", 1, lambda d: f"0x{d[0]:02X} (bit-encoded)"),
    0x61: ("Driver's demand engine torque", 1, num(lambda d: d[0] - 125, "%", "{:d}")),
    0x62: ("Actual engine torque", 1, num(lambda d: d[0] - 125, "%", "{:d}")),
    0x63: ("Engine reference torque", 2, num(u16, "N.m", "{:d}")),
    0x64: ("Engine percent torque data (idle + 4 points)", 5,
           lambda d: ", ".join(f"{x - 125} %" for x in d[:5])),
    0xA6: ("Odometer", 4, num(lambda d: int.from_bytes(bytes(d[:4]), "big") / 10, "km")),
}
for _i in range(8):
    PIDS[0x14 + _i] = (f"Oxygen sensor {_i + 1} (narrowband)", 2, o2_narrow)
    PIDS[0x24 + _i] = (f"Oxygen sensor {_i + 1} (wideband, voltage)", 4, o2_wide_v)
    PIDS[0x34 + _i] = (f"Oxygen sensor {_i + 1} (wideband, current)", 4, o2_wide_ma)

SUPPORT_PIDS = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0)
# PIDs whose last data byte is only sent when the vehicle has the second bank: pid -> fewest data bytes.
SHORT_OK = {0x55: 1, 0x56: 1, 0x57: 1, 0x58: 1}

INFOTYPES = {0x00: "Supported InfoTypes", 0x01: "VIN message count", 0x02: "Vehicle Identification Number (VIN)",
             0x03: "Calibration ID message count", 0x04: "Calibration IDs (CALID)",
             0x05: "CVN message count", 0x06: "Calibration Verification Numbers (CVN)",
             0x07: "In-use performance tracking message count", 0x08: "In-use performance tracking (spark)",
             0x09: "ECU name message count", 0x0A: "ECU name",
             0x0B: "In-use performance tracking (compression)"}


def supported(base, d):
    """Bitmask: the MSB of the first byte is PID base+1, the LSB of the fourth is base+0x20."""
    mask = int.from_bytes(bytes(d[:4]), "big")
    return [base + 1 + i for i in range(32) if mask >> (31 - i) & 1]


def dtc_text(b0, b1):
    """Two bytes -> 'P0133'. Top two bits pick the letter, next two the first digit, then three hex nibbles."""
    return f"{'PCBU'[b0 >> 6]}{(b0 >> 4) & 3}{b0 & 0x0F:X}{b1:02X}"


def dtc_bytes(text):
    t = text.strip().upper()
    if len(t) != 5 or t[0] not in "PCBU" or t[1] not in "0123":
        raise ValueError(f"not a DTC: {text!r} (expected e.g. P0133)")
    return bytes([("PCBU".index(t[0]) << 6) | (int(t[1]) << 4) | int(t[2], 16), int(t[3:], 16)])


def dtc_kind(code):
    system = {"P": "Powertrain", "C": "Chassis", "B": "Body", "U": "Network"}[code[0]]
    if code[0] == "P":
        scope = {"0": "generic (SAE)", "1": "manufacturer-specific", "2": "generic (SAE)",
                 "3": "manufacturer-specific (P3000-P33FF) or generic (P3400-P3FFF)"}[code[1]]
    else:
        scope = {"0": "generic (SAE)", "1": "manufacturer-specific", "2": "manufacturer-specific",
                 "3": "generic/reserved"}[code[1]]
    return f"{system}, {scope}"


def printable(bs):
    return "".join(chr(b) if 32 <= b < 127 else "" for b in bs).strip()


def decode_pid_stream(d, lines, freeze=False):
    """Mode 01/02 response body: PID [frame#] data, repeated (a CAN request may carry up to 6 PIDs)."""
    i = 0
    while i < len(d):
        pid = d[i]
        i += 1
        if freeze:
            if i >= len(d):
                break
            lines.append(f"  freeze frame #{d[i]}")
            i += 1
        if pid in SUPPORT_PIDS:
            if len(d) - i < 4:
                lines.append(f"  PID {pid:02X} MALFORMED: a supported-PID mask is 4 bytes, {len(d) - i} present")
                break
            pids = supported(pid, d[i:i + 4])
            lines.append(f"  PID {pid:02X} Supported PIDs {pid + 1:02X}-{pid + 0x20:02X}: "
                         + (" ".join(f"{p:02X}" for p in pids) or "none"))
            named = [f"{p:02X} {PIDS[p][0]}" for p in pids if p in PIDS]
            if named:
                lines.append("    " + "; ".join(named))
            i += 4
            continue
        if pid not in PIDS:
            lines.append(f"  PID {pid:02X}: not in the built-in table; raw data {bytes(d[i:]).hex(' ').upper()}")
            break
        name, n, fn = PIDS[pid]
        chunk = d[i:i + n]
        if len(chunk) < n and not (i + len(chunk) == len(d) and len(chunk) >= SHORT_OK.get(pid, n)):
            lines.append(f"  PID {pid:02X} {name}: MALFORMED, truncated (need {n} data bytes, have {len(chunk)})")
            break
        lines.append(f"  PID {pid:02X} {name}: {fn(chunk)}")
        i += n


def decode_dtcs(d, lines, can=True):
    """CAN (ISO 15765-4) replies start with a DTC count; K-line and J1850 replies are bare pairs. The two
    cannot be told apart from the bytes, so the caller says which, and a count that does not fit is an error."""
    if can:
        if not d:
            lines.append("  MALFORMED: no DTC count byte")
            return
        count, body = d[0], d[1:]
        if len(body) < 2 * count:
            lines.append(f"  MALFORMED: the count byte says {count} DTC(s) ({2 * count} bytes) but {len(body)} "
                         f"byte(s) follow. Truncated, or not a CAN reply (K-line/J1850 have no count byte: --legacy)")
            return
        lines.append(f"  {count} DTC(s) reported")
        if any(body[2 * count:]):
            lines.append(f"  note: ignored {len(body) - 2 * count} byte(s) after the last DTC "
                         f"({bytes(body[2 * count:]).hex(' ').upper()}): frame padding, or this is not a CAN reply")
        d = body[:2 * count]
    elif len(d) % 2:
        lines.append(f"  MALFORMED: {len(d)} byte(s) is not a whole number of 2-byte DTCs")
        return
    codes = [dtc_text(d[i], d[i + 1]) for i in range(0, len(d) - 1, 2) if d[i] or d[i + 1]]
    for c in codes:
        lines.append(f"  {c}  ({dtc_kind(c)})")
    if not codes:
        lines.append("  no DTCs")


def decode(payload, can=True):
    """Decode one OBD-II request or response payload. Returns a list of text lines; a line containing
    MALFORMED means the payload is too short for what it claims. can=False selects K-line/J1850 DTC framing."""
    p = bytes(payload)
    if not p:
        return ["empty payload"]
    sid = p[0]
    if sid == 0x7F:
        if len(p) < 3:
            return ["Negative response (truncated)"]
        return [f"Negative response to service {p[1]:02X} ({SERVICES.get(p[1], 'unknown')}): "
                f"NRC {p[2]:02X} {NRC.get(p[2], 'see the UDS NRC table')}"]
    if 0x01 <= sid <= 0x0A:
        lines = [f"Request, service {sid:02X}: {SERVICES[sid]}"]
        if sid in (0x01, 0x02):
            step = 2 if sid == 0x02 else 1
            for pid in p[1::step]:
                lines.append(f"  PID {pid:02X} {PIDS[pid][0] if pid in PIDS else 'supported-PID bitmask' if pid in SUPPORT_PIDS else ''}")
        elif sid == 0x09 and len(p) > 1:
            lines.append(f"  InfoType {p[1]:02X} {INFOTYPES.get(p[1], '')}")
        elif len(p) > 1:
            lines.append(f"  parameters: {p[1:].hex(' ').upper()}")
        return lines
    if not 0x41 <= sid <= 0x4A:
        return [f"Service byte {sid:02X} is not OBD-II (01-0A, 41-4A, 7F). "
                f"If it is UDS/KWP2000, see references/uds.md or run isotp_decode.py."]
    svc = sid - 0x40
    lines = [f"Response, service {svc:02X}: {SERVICES[svc]}"]
    d = list(p[1:])
    if svc == 0x01:
        decode_pid_stream(d, lines)
    elif svc == 0x02:
        decode_pid_stream(d, lines, freeze=True)
    elif svc in (0x03, 0x07, 0x0A):
        decode_dtcs(d, lines, can)
    elif svc == 0x04:
        lines.append("  DTCs, freeze frame and readiness monitors cleared")
    elif svc == 0x09 and d:
        it, body = d[0], d[1:]
        lines.append(f"  InfoType {it:02X} {INFOTYPES.get(it, '')}")
        if it == 0x00 and len(body) < 4:
            lines.append(f"  MALFORMED: a supported-InfoType mask is 4 bytes, {len(body)} present")
        elif it == 0x00:
            lines.append("  supported: " + " ".join(f"{x:02X}" for x in supported(0, body)))
        elif it in (0x02, 0x04, 0x0A) and body:
            items = body[1:]  # first byte is the number of data items (CAN)
            if it == 0x04:
                for k in range(0, len(items), 16):
                    lines.append(f"  CALID: {printable(items[k:k + 16])}")
            else:
                lines.append(f"  {'VIN' if it == 0x02 else 'ECU name'}: {printable(items)}")
        elif it == 0x06 and body:
            for k in range(1, len(body) - 3, 4):
                lines.append(f"  CVN: {bytes(body[k:k + 4]).hex().upper()}")
        else:
            lines.append(f"  data: {bytes(body).hex(' ').upper()}")
    elif svc == 0x06 and d:
        # CAN layout: OBDMID, then per test: TID, unit-and-scaling ID, value, min limit, max limit (16-bit each)
        if d[0] in SUPPORT_PIDS and len(d) < 5:
            lines.append(f"  MALFORMED: a supported-monitor mask is 4 bytes, {len(d) - 1} present")
        elif d[0] in SUPPORT_PIDS:
            lines.append(f"  supported monitor IDs: " + " ".join(f"{x:02X}" for x in supported(d[0], d[1:5])))
        else:
            for k in range(0, len(d) - 8, 9):
                r = d[k:k + 9]
                lines.append(f"  MID {r[0]:02X} TID {r[1]:02X} unit/scaling ID {r[2]:02X}: raw value {u16(r, 3)}, "
                             f"min {u16(r, 5)}, max {u16(r, 7)}  (scale per the unit/scaling ID table)")
    else:
        lines.append(f"  data: {bytes(d).hex(' ').upper()}")
    return lines


def self_test():
    assert decode(bytes.fromhex("410C1AF8"))[1].endswith("1726.00 rpm")
    assert "40 degC" in decode(bytes.fromhex("410550"))[1]
    assert "88 km/h" in decode(bytes.fromhex("410D58"))[1]
    # multi-PID response: rpm + speed in one message
    multi = decode(bytes.fromhex("410C1AF80D58"))
    assert len(multi) == 3 and "km/h" in multi[2]
    # BE 1F A8 13 -> the classic example bitmask
    assert supported(0, [0xBE, 0x1F, 0xA8, 0x13]) == \
        [0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x13, 0x15, 0x1C, 0x1F, 0x20]
    assert dtc_text(0x01, 0x33) == "P0133" and dtc_text(0xC1, 0x00) == "U0100"
    assert dtc_text(0x41, 0x23) == "C0123" and dtc_text(0x9A, 0xBC) == "B1ABC"
    for code in ("P0133", "U0100", "C0123", "B1ABC", "P3FFF"):
        assert dtc_text(*dtc_bytes(code)) == code
    out = decode(bytes.fromhex("43020133C100"))
    assert out[1].strip().startswith("2 DTC") and "P0133" in out[2] and "U0100" in out[3]
    assert "no DTCs" in decode(bytes.fromhex("4300"))[-1]
    vin = decode(bytes.fromhex("490201") + b"1G1JC5444R7252367")
    assert vin[-1].strip() == "VIN: 1G1JC5444R7252367", vin
    assert "serviceNotSupported" in decode(bytes.fromhex("7F0111"))[0]
    st = decode(bytes.fromhex("410181076504"))[1]
    assert "MIL ON, 1 confirmed" in st and "spark" in st and "Evaporative system" in st.split("NOT complete")[1], st
    assert "12.345 V" in decode(bytes.fromhex("41423039"))[1]
    assert "Request" in decode(bytes.fromhex("010C"))[0]
    assert pid_value(0x0C, [0x1A, 0xF8]) == 1726.0 and pid_value(0x05, [0x50]) == 40.0
    assert pid_value(0x01, [0, 0, 0, 0]) is None and pid_value(0x0C, [0x1A]) is None
    # nothing is invented from a short reply: a 1-byte mask, and a DTC count with too few bytes behind it
    assert "MALFORMED" in decode(bytes.fromhex("410080"))[1] and "MALFORMED" in decode(bytes.fromhex("43020133"))[1]
    assert "MALFORMED" in decode(bytes.fromhex("410C1A"))[1]
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["43", "02", "01", "33"]) == 1 and main(["43", "01", "01", "33"]) == 0
    # CAN frame padding after the DTCs is not read as more codes; legacy replies have no count byte
    assert [l.split()[0] for l in decode(bytes.fromhex("4301013300000000"))[2:]] == ["P0133"]
    assert "P0133" in decode(bytes.fromhex("43013300000000"), can=False)[1]
    # PID 41: enabled and complete are separate; here catalyst is enabled and not complete, EVAP not enabled
    st = decode(bytes.fromhex("414100070101"))[1]
    assert "NOT complete: Catalyst;" in st and "not enabled" in st and "Evaporative" in st.split("not enabled")[1], st
    assert decode(bytes.fromhex("415580"))[1].endswith("+0.0 %") and "MALFORMED" not in decode(bytes.fromhex("41558080"))[1]
    print("self-test OK")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("hex", nargs="*", help="payload bytes, starting with the service byte")
    ap.add_argument("--dtc", help="convert a DTC: 'P0133' -> bytes, or two bytes '0133' -> text")
    ap.add_argument("--pids", action="store_true", help="list the built-in Mode 01 PID table")
    ap.add_argument("--legacy", action="store_true",
                    help="the reply came from K-line or J1850, not CAN: service 03/07/0A carries no DTC count byte")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if a.pids:
        for pid in sorted(set(PIDS) | set(SUPPORT_PIDS)):
            if pid in SUPPORT_PIDS:
                print(f"{pid:02X}  4  Supported PIDs {pid + 1:02X}-{pid + 0x20:02X} (bitmask)")
            else:
                print(f"{pid:02X}  {PIDS[pid][1]}  {PIDS[pid][0]}")
        return 0
    try:
        if a.dtc:
            t = a.dtc.replace(" ", "")
            if t[0].upper() in "PCBU" and len(t) == 5:
                b = dtc_bytes(t)
                print(f"{t.upper()} = bytes {b.hex(' ').upper()}  ({dtc_kind(t.upper())})")
            else:
                b = bytes.fromhex(t)
                code = dtc_text(b[0], b[1])
                print(f"{b[:2].hex(' ').upper()} = {code}  ({dtc_kind(code)})")
            return 0
        if not a.hex:
            ap.error("give payload hex bytes, or --dtc / --pids / --self-test")
        payload = bytes.fromhex("".join(a.hex).replace("0x", "").replace(",", ""))
    except (ValueError, IndexError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    lines = decode(payload, can=not a.legacy)
    print("\n".join(lines))
    return 1 if any("MALFORMED" in line for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
