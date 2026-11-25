#!/usr/bin/env python3
"""ISO-TP (ISO 15765-2) reassembler and OBD-II / UDS / KWP2000 annotator.

Reads a capture (candump log, candump console output, SavvyCAN CSV), rebuilds
multi-frame diagnostic messages, and labels each one: service name, negative
response code, DIDs, OBD-II PID values.

    isotp_decode.py capture.log                 # diagnostic IDs: 0x700-0x7FF, 18DAxxxx, 18DBxxxx
    isotp_decode.py capture.log --ids 7E0,7E8   # only these IDs
    isotp_decode.py capture.log --all           # try every ID on the bus
    isotp_decode.py capture.log --ext-addr      # extended/mixed addressing: data byte 0 is an address
    isotp_decode.py capture.log -v              # also show flow-control frames and stray-frame errors
    isotp_decode.py capture.log --bus can0      # a log recorded from several interfaces: one bus at a time

A multi-frame message with a missing consecutive frame is reported as BROKEN and
not decoded; one that never finishes is reported as INCOMPLETE.
    isotp_decode.py --self-test

Use it to read what a scan tool asked an ECU and what came back: capture while
the tool displays a value, then find the request/response pair that carries it.

Standard library only. Python 3.8+. Needs can_log_analyze.py and obd_decode.py
from the same directory.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_log_analyze import fmt_id, load  # noqa: E402
import obd_decode  # noqa: E402

UDS = {
    0x10: "DiagnosticSessionControl", 0x11: "ECUReset", 0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation", 0x22: "ReadDataByIdentifier", 0x23: "ReadMemoryByAddress",
    0x24: "ReadScalingDataByIdentifier", 0x27: "SecurityAccess", 0x28: "CommunicationControl",
    0x29: "Authentication", 0x2A: "ReadDataByPeriodicIdentifier", 0x2C: "DynamicallyDefineDataIdentifier",
    0x2E: "WriteDataByIdentifier", 0x2F: "InputOutputControlByIdentifier", 0x31: "RoutineControl",
    0x34: "RequestDownload", 0x35: "RequestUpload", 0x36: "TransferData", 0x37: "RequestTransferExit",
    0x38: "RequestFileTransfer", 0x3D: "WriteMemoryByAddress", 0x3E: "TesterPresent",
    0x83: "AccessTimingParameter", 0x84: "SecuredDataTransmission", 0x85: "ControlDTCSetting",
    0x86: "ResponseOnEvent", 0x87: "LinkControl",
}
# Services that exist in KWP2000 (ISO 14230) but not UDS; seen on pre-~2008 ECUs and some later ones.
KWP = {
    0x12: "ReadFreezeFrameData (KWP2000)", 0x13: "ReadDiagnosticTroubleCodes (KWP2000)",
    0x17: "ReadStatusOfDTC (KWP2000)", 0x18: "ReadDTCByStatus (KWP2000)",
    0x1A: "ReadEcuIdentification (KWP2000)", 0x20: "StopDiagnosticSession (KWP2000)",
    0x21: "ReadDataByLocalIdentifier (KWP2000)", 0x30: "InputOutputControlByLocalIdentifier (KWP2000)",
    0x32: "StopRoutineByLocalIdentifier (KWP2000)", 0x33: "RequestRoutineResultsByLocalIdentifier (KWP2000)",
    0x3B: "WriteDataByLocalIdentifier (KWP2000)", 0x81: "StartCommunication (KWP2000)",
    0x82: "StopCommunication (KWP2000)",
}
NRC = {
    0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat", 0x14: "responseTooLong", 0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect", 0x24: "requestSequenceError", 0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction", 0x31: "requestOutOfRange",
    0x33: "securityAccessDenied", 0x34: "authenticationRequired", 0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts", 0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted", 0x71: "transferDataSuspended", 0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter", 0x78: "requestCorrectlyReceived-ResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession", 0x7F: "serviceNotSupportedInActiveSession",
    0x81: "rpmTooHigh", 0x82: "rpmTooLow", 0x83: "engineIsRunning", 0x84: "engineIsNotRunning",
    0x85: "engineRunTimeTooLow", 0x86: "temperatureTooHigh", 0x87: "temperatureTooLow",
    0x88: "vehicleSpeedTooHigh", 0x89: "vehicleSpeedTooLow", 0x8A: "throttle/PedalTooHigh",
    0x8B: "throttle/PedalTooLow", 0x8C: "transmissionRangeNotInNeutral", 0x8D: "transmissionRangeNotInGear",
    0x8F: "brakeSwitch(es)NotClosed", 0x90: "shifterLeverNotInPark", 0x91: "torqueConverterClutchLocked",
    0x92: "voltageTooHigh", 0x93: "voltageTooLow",
}
SESSIONS = {1: "default", 2: "programming", 3: "extended", 4: "safety system"}
RESETS = {1: "hardReset", 2: "keyOffOnReset", 3: "softReset"}
DIDS = {0xF180: "boot software ID", 0xF181: "application software ID", 0xF182: "application data ID",
        0xF186: "active diagnostic session", 0xF187: "spare part number", 0xF188: "ECU software number",
        0xF189: "ECU software version", 0xF18A: "system supplier ID", 0xF18B: "ECU manufacturing date",
        0xF18C: "ECU serial number", 0xF190: "VIN", 0xF191: "ECU hardware number",
        0xF192: "supplier ECU hardware number", 0xF193: "supplier ECU hardware version",
        0xF194: "supplier ECU software number", 0xF195: "supplier ECU software version",
        0xF197: "system name or engine type", 0xF198: "repair shop code / tester serial",
        0xF199: "programming date", 0xF19E: "ODX file ID"}
FLOW_STATUS = {0: "ContinueToSend", 1: "Wait", 2: "Overflow"}


def name_of(sid):
    return UDS.get(sid) or KWP.get(sid) or f"service 0x{sid:02X}"


def ascii_hint(bs):
    if len(bs) >= 4 and all(32 <= b < 127 for b in bs):
        return f' "{bytes(bs).decode("ascii")}"'
    return ""


def describe(p):
    """One-line meaning of a reassembled diagnostic payload."""
    if not p:
        return ""
    sid = p[0]
    if sid == 0x7F and len(p) >= 3:
        note = "  (not an error: the ECU needs more time, keep waiting)" if p[2] == 0x78 else ""
        return f"NEGATIVE response to {name_of(p[1])}: NRC 0x{p[2]:02X} {NRC.get(p[2], 'manufacturer/reserved')}{note}"
    if 0x01 <= sid <= 0x0A or 0x41 <= sid <= 0x4A:
        return " | ".join(s.strip() for s in obd_decode.decode(p))
    resp = (0x50 <= sid <= 0x7E or 0xC1 <= sid <= 0xC7) and (sid - 0x40) in {**UDS, **KWP}
    base = sid - 0x40 if resp else sid
    text = ("+ " if resp else "> ") + name_of(base)
    a = p[1:]
    if base == 0x10 and a:
        text += f": session 0x{a[0] & 0x7F:02X} {SESSIONS.get(a[0] & 0x7F, 'OEM-specific')}"
        if resp and len(a) >= 5:
            text += f", P2 {(a[1] << 8) | a[2]} ms, P2* {((a[3] << 8) | a[4]) * 10} ms"
    elif base == 0x11 and a:
        text += f": {RESETS.get(a[0] & 0x7F, f'type 0x{a[0]:02X}')}"
    elif base == 0x22:
        if resp and len(a) >= 2:
            did = (a[0] << 8) | a[1]
            text += f": DID {did:04X}{' (' + DIDS[did] + ')' if did in DIDS else ''} = {bytes(a[2:]).hex(' ').upper()}{ascii_hint(a[2:])}"
        else:
            dids = [(a[i] << 8) | a[i + 1] for i in range(0, len(a) - 1, 2)]
            text += ": DID " + ", ".join(f"{d:04X}{' (' + DIDS[d] + ')' if d in DIDS else ''}" for d in dids)
    elif base == 0x2E and len(a) >= 2:
        text += f": DID {(a[0] << 8) | a[1]:04X}" + ("" if resp else f" <- {bytes(a[2:]).hex(' ').upper()}")
    elif base == 0x27 and a:
        lvl = a[0] & 0x7F
        if lvl % 2:
            text += f": {'seed' if resp else 'requestSeed'} level 0x{lvl:02X}" + \
                    (f" seed={bytes(a[1:]).hex().upper()}" + (" (all zero: already unlocked)" if resp and not any(a[1:]) else "") if resp else "")
        else:
            text += f": {'key accepted' if resp else 'sendKey'} level 0x{lvl:02X}" + \
                    ("" if resp else f" key={bytes(a[1:]).hex().upper()}")
    elif base == 0x3E:
        text += " (response suppressed)" if a and a[0] & 0x80 else ""
    elif base == 0x19 and a:
        text += f": subfunction 0x{a[0]:02X}"
        if resp and a[0] in (0x02, 0x0A, 0x15) and len(a) >= 2:
            recs = a[2:]
            codes = [f"{obd_decode.dtc_text(recs[i], recs[i + 1])}-{recs[i + 2]:02X} status 0x{recs[i + 3]:02X}"
                     for i in range(0, len(recs) - 3, 4)]
            text += f", availability mask 0x{a[1]:02X}: " + (", ".join(codes) or "no DTCs")
    elif base == 0x31 and len(a) >= 3:
        text += f": {({1: 'start', 2: 'stop', 3: 'requestResults'}).get(a[0] & 0x7F, hex(a[0]))} routine {(a[1] << 8) | a[2]:04X}"
    elif base == 0x14 and not resp and len(a) >= 3:
        text += f": group {bytes(a[:3]).hex().upper()}" + (" (all DTCs)" if bytes(a[:3]) == b"\xff\xff\xff" else "")
    elif base in (0x21, 0x1A) and a:
        text += f": local ID 0x{a[0]:02X}" + (f" = {bytes(a[1:]).hex(' ').upper()}{ascii_hint(a[1:])}" if resp else "")
    elif a:
        text += f": {bytes(a[:24]).hex(' ').upper()}" + (" ..." if len(a) > 24 else "")
    return text


class Reassembler:
    """One instance per CAN ID (per direction). feed() returns (kind, value) events."""

    def __init__(self):
        self.buf = None
        self.want = 0
        self.seq = 0
        self.cfs = 0      # consecutive frames taken into the current message

    def feed(self, d):
        if not d:
            return []
        kind = d[0] >> 4
        if kind == 0:  # single frame
            n, start = d[0] & 0x0F, 1
            if n == 0 and len(d) > 8:  # CAN FD escape: length in the next byte
                n, start = d[1], 2
            if n == 0 or start + n > len(d):
                return [("err", f"bad single-frame length {n}")]
            ev = [("drop", (self.want, bytes(self.buf), self.cfs))] if self.buf is not None else []
            self.buf = None
            return ev + [("msg", bytes(d[start:start + n]))]
        if kind == 1:  # first frame
            if len(d) < 2:
                return [("err", "truncated first frame")]
            n, start = ((d[0] & 0x0F) << 8) | d[1], 2
            if n == 0:  # escape: 32-bit length follows
                if len(d) < 6:
                    return [("err", "truncated first frame")]
                n, start = int.from_bytes(d[2:6], "big"), 6
            ev = [("drop", (self.want, bytes(self.buf), self.cfs))] if self.buf is not None else []
            self.buf, self.want, self.seq, self.cfs = bytearray(d[start:]), n, 1, 0
            return ev + [("ff", n)]
        if kind == 2:  # consecutive frame
            if self.buf is None:
                return [("err", "consecutive frame with no first frame (capture started mid-message?)")]
            if d[0] & 0x0F != self.seq:
                # A gap cannot be patched over: every byte after it would land in the wrong place, and the
                # result would still look like a valid message. Abandon the message and say so.
                ev = [("bad", (self.want, bytes(self.buf), self.seq, d[0] & 0x0F))]
                self.buf = None
                return ev
            self.seq = (self.seq + 1) & 0x0F
            self.cfs += 1
            self.buf += d[1:]
            if len(self.buf) >= self.want:
                msg, self.buf = bytes(self.buf[:self.want]), None
                return [("msg", msg)]
            return []
        if kind == 3:  # flow control
            st = d[2] if len(d) > 2 else 0
            if st <= 0x7F:
                stmin = f"{st} ms"
            elif 0xF1 <= st <= 0xF9:
                stmin = f"{(st - 0xF0) * 100} us"
            else:
                stmin = f"reserved 0x{st:02X}"
            bs = d[1] if len(d) > 1 else 0
            return [("fc", f"FlowControl {FLOW_STATUS.get(d[0] & 0x0F, 'reserved')}, "
                           f"block size {bs}{' (no limit)' if bs == 0 else ''}, STmin {stmin}")]
        return [("err", f"not ISO-TP (PCI nibble {kind:X})")]


def incomplete(ts, ident, t0, want, buf, cfs, fc_seen):
    """A first frame whose message never finished. Says only what the capture shows about why."""
    pad = " " * 31
    if cfs:
        why = (f"{cfs} consecutive frame(s) arrived and then the transfer stopped: the capture ended, frames "
               f"were lost, or the sender gave up.")
    elif fc_seen:
        why = ("A flow-control frame follows the first frame in this capture, yet no consecutive frame (2x) was "
               "captured: frames were lost or filtered out, or the sender did not accept the flow control.")
    else:
        why = ("No consecutive frame (2x) and no flow control (30 xx xx) follow it among the frames examined. If "
               "both directions were captured, the receiver never sent flow control on the sender's physical "
               "request ID. A one-directional or ID-filtered capture cannot show which.")
    return (ts, f"{ts - t0:9.3f}  {ident:>8}  [{want:>4}]  {buf[:6].hex(' ').upper()} ...\n"
                f"{pad}INCOMPLETE multi-frame message: first frame announced {want} bytes, only {len(buf)} received."
                f"\n{pad}Starts as (first frame only): {describe(buf[:6])}\n{pad}{why}")


def broken(ts, ident, t0, want, buf, expected, got):
    """A multi-frame message with a gap in its consecutive frames. It is reported, never decoded."""
    pad = " " * 31
    return (ts, f"{ts - t0:9.3f}  {ident:>8}  [{want:>4}]  {buf[:6].hex(' ').upper()} ...\n"
                f"{pad}BROKEN multi-frame message: after {len(buf)} of {want} bytes the next consecutive frame "
                f"should be 2{expected:X} but is 2{got:X}.\n{pad}A frame is missing (lost by the capture, or never "
                f"sent), so the message is not decoded.\n{pad}Starts as (first frame only): {describe(buf[:6])}")


def is_diag_id(can_id, ext):
    if ext:
        return (can_id >> 16) in (0x18DA, 0x18DB)
    return 0x700 <= can_id <= 0x7FF


def run(path, ids=None, all_ids=False, ext_addr=False, verbose=False, bus=None):
    lines, t0, state, started, last_fc, timed = [], None, {}, {}, -1, True
    for n, f in enumerate(load(path, bus)):
        if ids is not None:
            if f.can_id not in ids:
                continue
        elif not all_ids and not is_diag_id(f.can_id, f.ext):
            continue
        t0, timed = (f.ts, f.timed) if t0 is None else (t0, timed)
        data, key, addr = f.data, (f.can_id, f.ext), ""
        if ext_addr:
            if len(data) < 2:
                continue
            key, addr, data = key + (data[0],), f"[{data[0]:02X}]", data[1:]
        ident = f"{fmt_id(f.can_id, f.ext)}{addr}"
        for kind, val in state.setdefault(key, Reassembler()).feed(data):
            if kind == "msg":
                lines.append((f.ts, f"{f.ts - t0:9.3f}  {ident:>8}  [{len(val):>4}]  "
                                    f"{val[:32].hex(' ').upper()}{' ...' if len(val) > 32 else ''}\n"
                                    f"{'':31}{describe(val)}"))
            elif kind == "ff":
                started[key] = (f.ts, ident, n)
            elif kind == "drop":
                lines.append(incomplete(*started[key][:2], t0, *val, last_fc > started[key][2]))
            elif kind == "bad":
                lines.append(broken(*started[key][:2], t0, *val))
            else:
                if kind == "fc":
                    last_fc = n
                if verbose and not (all_ids and kind == "err"):
                    lines.append((f.ts, f"{f.ts - t0:9.3f}  {ident:>8}          {val}"))
    for key, r in state.items():
        if r.buf is not None:
            lines.append(incomplete(*started[key][:2], t0, r.want, bytes(r.buf), r.cfs, last_fc > started[key][2]))
    out = [text for _, text in sorted(lines, key=lambda x: x[0])]
    if out and not timed:
        out.insert(0, "note: the file has no timestamps; the time column only shows frame order (1 ms per frame)")
    return out


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        _self_test(os.path.join(d, "t.log"))
    print("self-test OK")


def _self_test(path):
    vin = b"1G1JC5444R7252367"
    resp = bytes.fromhex("490201") + vin  # 20 bytes -> FF + 2 CF
    log = [
        "(100.000000) can0 7DF#0209020000000000",
        f"(100.010000) can0 7E8#1014{resp[:6].hex()}",
        "(100.011000) can0 7E0#3000000000000000",
        f"(100.012000) can0 7E8#21{resp[6:13].hex()}",
        f"(100.013000) can0 7E8#22{resp[13:20].hex()}",
        "(100.100000) can0 7E0#0322F19000000000",
        "(100.110000) can0 7E8#037F227800000000",
        "(100.120000) can0 7E8#037F223100000000",
        "(100.200000) can0 7E0#021003AAAAAAAAAA",
        "(100.210000) can0 7E8#065003003201F4AA",
        "(100.300000) can0 123#1122334455667788",
        "(100.400000) can0 18DAF110#0462F18612000000",
        "(100.500000) can0 7E8#2100000000000000",
    ]
    with open(path, "w") as fh:
        fh.write("\n".join(log) + "\n")
    out = "\n".join(run(path, verbose=True))
    assert "VIN: 1G1JC5444R7252367" in out, out
    assert "FlowControl ContinueToSend, block size 0 (no limit), STmin 0 ms" in out, out
    assert "> ReadDataByIdentifier: DID F190 (VIN)" in out, out
    assert "ResponsePending" in out and "keep waiting" in out
    assert "NRC 0x31 requestOutOfRange" in out
    assert "session 0x03 extended, P2 50 ms, P2* 5000 ms" in out, out
    assert "DID F186 (active diagnostic session) = 12" in out, out
    assert "consecutive frame with no first frame" in out and "INCOMPLETE" not in out
    assert "123" not in out.replace("0123", "")  # non-diagnostic ID is ignored by default
    assert len(run(path, ids={0x7E0})) == 2
    # a first frame that is never followed by consecutive frames is reported, with what it started to say
    with open(path, "w") as fh:
        fh.write("7DF#0209020000000000\n7E8#101449020157304C\n7DF#02010C0000000000\n7E8#04410C0BB8AAAAAA\n")
    out = "\n".join(run(path))
    assert "INCOMPLETE" in out and "announced 20 bytes, only 6" in out and "flow control" in out, out
    assert out.index("INCOMPLETE") < out.index("750.00 rpm"), out
    # CAN FD single frame with the escape length byte, and extended addressing
    r = Reassembler()
    assert r.feed(bytes([0x00, 0x0A]) + bytes(range(10)) + bytes(4)) == [("msg", bytes(range(10)))]
    with open(path, "w") as fh:
        fh.write("(1.0) can0 6F1#12023E0000000000\n(1.1) can0 612#F1027E0000000000\n")
    out = "\n".join(run(path, all_ids=True, ext_addr=True))
    assert "6F1[12]" in out and "> TesterPresent" in out and "+ TesterPresent" in out, out
    # a missing consecutive frame (21 then 23) must not produce a decoded message
    ff, fc = f"(1.0) can0 7E8#1014{resp[:6].hex()}\n", "(1.1) can0 7E0#3000000000000000\n"
    with open(path, "w") as fh:
        fh.write(ff + fc + f"(1.2) can0 7E8#21{resp[6:13].hex()}\n(1.3) can0 7E8#23{resp[13:20].hex()}\n")
    out = "\n".join(run(path))
    assert "BROKEN" in out and "should be 22 but is 23" in out and vin.decode() not in out, out
    # flow control is in the capture, so its absence must not be given as the cause
    with open(path, "w") as fh:
        fh.write(ff + fc)
    out = "\n".join(run(path))
    assert "INCOMPLETE" in out and "A flow-control frame follows" in out and "never sent" not in out, out
    # frames from another bus must not be stitched into the message
    with open(path, "w") as fh:
        fh.write(ff + f"(1.2) can1 7E8#21{resp[6:13].hex()}\n(1.3) can1 7E8#22{resp[13:20].hex()}\n")
    try:
        run(path)
        raise AssertionError("two buses should be refused")
    except SystemExit:
        pass
    assert "INCOMPLETE" in "\n".join(run(path, bus="can0"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?")
    ap.add_argument("--ids", help="comma-separated hex CAN IDs to decode")
    ap.add_argument("--all", action="store_true", help="try every CAN ID (hides per-ID parse errors)")
    ap.add_argument("--ext-addr", action="store_true",
                    help="extended or mixed addressing: first data byte is an address, PCI follows")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="also show flow-control frames and stray-frame errors")
    ap.add_argument("--bus", help="interface name (can0) or CSV bus number to decode, when the file holds several")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if not a.log:
        ap.error("a log file is required")
    try:
        ids = {int(x, 16) for x in a.ids.split(",")} if a.ids else None
    except ValueError:
        ap.error(f"--ids takes comma-separated hex CAN IDs, got {a.ids!r}")
    lines = run(a.log, ids, a.all, a.ext_addr, a.verbose, a.bus)
    if not lines:
        print("No ISO-TP messages found. Try --all (non-standard IDs), --ext-addr (BMW-style addressing), "
              "or check that the capture includes the tester's requests.", file=sys.stderr)
        return 1
    print("   time        ID    len   payload / meaning   (> request, + positive response)")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
