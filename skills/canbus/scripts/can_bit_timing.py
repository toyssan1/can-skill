#!/usr/bin/env python3
"""CAN / CAN FD bit-timing calculator.

For every prescaler the controller offers, takes the number of time quanta that
comes closest to the bitrate, splits it at the point nearest the wanted sample
point, and drops anything the controller cannot be programmed with. The
survivors are ranked by bitrate error, then sample-point error, and printed with
register values. They are ranked candidates, not a proof that nothing else works.

    can_bit_timing.py --profile mcp2515 --clock 8e6 --bitrate 500k
    can_bit_timing.py --profile twai --clock 80e6 --bitrate 250k --sample-point 80
    can_bit_timing.py --profile mcan --clock 40e6 --bitrate 500k --data-bitrate 2M
    can_bit_timing.py --self-test

--clock is the frequency fed to the CAN core: the crystal for MCP2515/SJA1000,
the APB/XTAL source for ESP32 TWAI, PCLK1 for STM32 bxCAN, the FDCAN kernel
clock for M_CAN, SYSCLK (after any PLL) for MCP2517FD/MCP2518FD.

Standard library only. Python 3.8+.
"""
import argparse
import sys

# Limits are real segment lengths in time quanta (not register values, which
# are usually "minus one"). brp = (min, max, step). clock_div is a fixed divider
# in front of the prescaler (MCP2515 and SJA1000: TQ = 2 * BRP / Fosc).
PROFILES = {
    "generic": dict(desc="No controller limits (use for Linux `ip link ... tq`)",
                    clock_div=1, brp=(1, 1024, 1), tseg1=(1, 256), tseg2=(1, 128), sjw=128),
    "mcp2515": dict(desc="Microchip MCP2515 / MCP25625 (clock = crystal)",
                    clock_div=2, brp=(1, 64, 1), tseg1=(2, 16), tseg2=(2, 8), sjw=4,
                    # Datasheet section 5.5: PropSeg + PS1 >= PS2, and PS2 >= SJW (revision K; earlier
                    # revisions said PS2 > SJW, and the common library tables use SJW 1, so that stays
                    # the default. --sjw may ask for as much as PS2).
                    tseg1_ge_tseg2=True, default_sjw_below_tseg2=True),
    "sja1000": dict(desc="NXP SJA1000 and clones (clock = crystal)",
                    clock_div=2, brp=(1, 64, 1), tseg1=(1, 16), tseg2=(1, 8), sjw=4),
    "twai": dict(desc="ESP32 TWAI, legacy driver twai_timing_config_t (clock = 80 MHz APB "
                      "on ESP32/S2/S3/C3; check the clock source on newer chips)",
                 clock_div=1, brp=(2, 128, 2), tseg1=(1, 16), tseg2=(1, 8), sjw=4),
    "bxcan": dict(desc="STM32 bxCAN, F0/F1/F2/F3/F4/F7/L4 (clock = PCLK1)",
                  clock_div=1, brp=(1, 1024, 1), tseg1=(1, 16), tseg2=(1, 8), sjw=4),
    "mcan": dict(desc="Bosch M_CAN: STM32 FDCAN, TCAN4550, SAM C21/E5x (clock = CAN kernel clock)",
                 clock_div=1, brp=(1, 512, 1), tseg1=(2, 256), tseg2=(2, 128), sjw=128,
                 # M_CAN manual 3.3.1, DBTP: DTSEG2 valid values 1-15, so data segment 2 is 2-16 TQ.
                 # With transmitter delay compensation on, DBRP may only be 0 or 1 (prescaler 1 or 2).
                 data=dict(brp=(1, 32, 1), tseg1=(1, 32), tseg2=(2, 16), sjw=16, tdc_brp_max=2)),
    "mcp2518fd": dict(desc="Microchip MCP2517FD / MCP2518FD / MCP251863 (clock = SYSCLK, 20 or 40 MHz)",
                      clock_div=1, brp=(1, 256, 1), tseg1=(2, 256), tseg2=(1, 128), sjw=128,
                      data=dict(brp=(1, 256, 1), tseg1=(1, 32), tseg2=(1, 16), sjw=16)),
}


def parse_num(text):
    """'500k' -> 500000, '2M' -> 2000000, '8e6' -> 8000000."""
    t = text.strip().lower().replace("hz", "").replace("bps", "").replace("bit/s", "")
    mult = 1
    if t.endswith("k"):
        mult, t = 1_000, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    return float(t) * mult


def default_sample_point(bitrate):
    """Same rule the Linux kernel uses (CiA-derived): 87.5% up to 500k, 80% up to 800k, else 75%."""
    if bitrate > 800_000:
        return 0.75
    if bitrate > 500_000:
        return 0.80
    return 0.875


def candidates(clock, bitrate, sample_point, lim, clock_div=1, max_err=0.0, sjw=None):
    """One timing per usable prescaler (the split nearest the sample point), best first."""
    out = []
    f = clock / clock_div
    lo, hi, step = lim["brp"]
    t1min, t1max = lim["tseg1"]
    t2min, t2max = lim["tseg2"]
    for brp in range(lo, hi + 1, step):
        ntq = round(f / (brp * bitrate))
        if not (1 + t1min + t2min) <= ntq <= (1 + t1max + t2max):
            continue
        actual = f / (brp * ntq)
        err = (actual - bitrate) / bitrate
        if abs(err) > max_err + 1e-12:
            continue
        best = None
        for tseg2 in range(t2min, t2max + 1):
            tseg1 = ntq - 1 - tseg2
            if not t1min <= tseg1 <= t1max or (lim.get("tseg1_ge_tseg2") and tseg1 < tseg2):
                continue
            sp = (1 + tseg1) / ntq
            if best is None or abs(sp - sample_point) < abs(best["sp"] - sample_point):
                best = dict(brp=brp, ntq=ntq, tseg1=tseg1, tseg2=tseg2, sp=sp,
                            bitrate=actual, err=err, tq_ns=1e9 * brp * clock_div / clock)
        if best:
            cap = best["tseg2"]                      # SJW may never exceed phase segment 2
            want = sjw or (cap - 1 if lim.get("default_sjw_below_tseg2") else cap)
            best["sjw"] = max(1, min(want, lim["sjw"], cap))
            out.append(best)
    out.sort(key=lambda c: (round(abs(c["err"]), 6), round(abs(c["sp"] - sample_point), 4), c["brp"]))
    return out


def mcp2515_cnf(c):
    """CNF1..3 with BTLMODE=1, SAM=0, SOF/WAKFIL=0. Sample point sits at the end of PS1."""
    prop = min(8, (c["tseg1"] + 1) // 2)
    ps1 = c["tseg1"] - prop
    cnf1 = ((c["sjw"] - 1) << 6) | (c["brp"] - 1)
    cnf2 = 0x80 | ((ps1 - 1) << 3) | (prop - 1)
    cnf3 = c["tseg2"] - 1
    return cnf1, cnf2, cnf3, prop, ps1


def registers(profile, c, data=False):
    """Controller-specific register / struct rendering for one candidate."""
    b, t1, t2, s = c["brp"], c["tseg1"], c["tseg2"], c["sjw"]
    if profile == "mcp2515":
        cnf1, cnf2, cnf3, prop, ps1 = mcp2515_cnf(c)
        return (f"CNF1=0x{cnf1:02X} CNF2=0x{cnf2:02X} CNF3=0x{cnf3:02X}  "
                f"(PRSEG={prop} PS1={ps1} PS2={t2} SJW={s} BRP={b})")
    if profile == "sja1000":
        btr0 = ((s - 1) << 6) | (b - 1)
        btr1 = ((t2 - 1) << 4) | (t1 - 1)
        return f"BTR0=0x{btr0:02X} BTR1=0x{btr1:02X}"
    if profile == "twai":
        return f"twai_timing_config_t t = {{.brp = {b}, .tseg_1 = {t1}, .tseg_2 = {t2}, .sjw = {s}}};"
    if profile == "bxcan":
        btr = ((s - 1) << 24) | ((t2 - 1) << 20) | ((t1 - 1) << 16) | (b - 1)
        return f"CAN_BTR=0x{btr:08X}  (HAL: Prescaler={b} BS1={t1}TQ BS2={t2}TQ SJW={s}TQ)"
    if profile == "mcan":
        if data:
            reg = ((b - 1) << 16) | ((t1 - 1) << 8) | ((t2 - 1) << 4) | (s - 1)
            return (f"DBTP=0x{reg:08X} (TDC bit not set)  "
                    f"(HAL: DataPrescaler={b} DataTimeSeg1={t1} DataTimeSeg2={t2} DataSyncJumpWidth={s})")
        reg = ((s - 1) << 25) | ((b - 1) << 16) | ((t1 - 1) << 8) | (t2 - 1)
        return (f"NBTP=0x{reg:08X}  "
                f"(HAL: NominalPrescaler={b} NominalTimeSeg1={t1} NominalTimeSeg2={t2} NominalSyncJumpWidth={s})")
    if profile == "mcp2518fd":
        reg = ((b - 1) << 24) | ((t1 - 1) << 16) | ((t2 - 1) << 8) | (s - 1)
        return f"{'CiDBTCFG' if data else 'CiNBTCFG'}=0x{reg:08X}"
    # generic: Linux netlink wants tq in ns and the segments split out
    prop = t1 // 2
    return (f"ip link set canX type can tq {round(c['tq_ns'])} prop-seg {prop} "
            f"phase-seg1 {t1 - prop} phase-seg2 {t2} sjw {s}")


def fmt(c, asked_sjw=None):
    text = (f"BRP={c['brp']:<4} TQ={c['tq_ns']:8.2f} ns  NTQ={c['ntq']:<3} "
            f"TSEG1={c['tseg1']:<3} TSEG2={c['tseg2']:<3} SJW={c['sjw']:<3} "
            f"SP={100 * c['sp']:5.1f}%  bitrate={c['bitrate']:.0f} ({100 * c['err']:+.3f}%)")
    if asked_sjw and asked_sjw != c["sjw"]:
        text += (f"\n      NOTE: --sjw {asked_sjw} is not possible here (the limit is {c['sjw']}: SJW cannot exceed "
                 f"TSEG2 or the controller's maximum). Shown with SJW={c['sjw']}.")
    return text


def report(profile, clock, bitrate, sp, top, max_err, data_bitrate=None, data_sp=None, sjw=None):
    p = PROFILES[profile]
    lines = [f"Profile: {profile} - {p['desc']}",
             f"Clock: {clock:.0f} Hz   Nominal bitrate: {bitrate:.0f}   Target sample point: {100 * sp:.1f}%"]
    nom = candidates(clock, bitrate, sp, p, p["clock_div"], max_err, sjw)
    if not nom:
        lines.append("No valid nominal timing. Try --max-error 0.5, or this clock cannot make this bitrate.")
        return "\n".join(lines), 1
    lines.append("\nNominal (arbitration) phase, best first:")
    for c in nom[:top]:
        lines.append("  " + fmt(c, sjw))
        lines.append("      " + registers(profile, c))
    if data_bitrate:
        if "data" not in p:
            lines.append(f"\nProfile '{profile}' is classical CAN only; no data-phase timing.")
            return "\n".join(lines), 1
        dsp = data_sp or default_sample_point(data_bitrate)
        dat = candidates(clock, data_bitrate, dsp, p["data"], p["clock_div"], max_err, sjw)
        lines.append(f"\nData phase: {data_bitrate:.0f} bit/s, target sample point {100 * dsp:.1f}%, best first:")
        if not dat:
            lines.append("  No valid data-phase timing for this clock.")
            return "\n".join(lines), 1
        tdc_max = p["data"].get("tdc_brp_max")
        if tdc_max and data_bitrate > 1e6:       # the rates at which TDC is needed
            usable = [d for d in dat if d["brp"] <= tdc_max]
            if usable:
                dat = usable
                lines.append(f"  (only prescalers up to {tdc_max} are listed: this controller cannot use "
                             f"transmitter delay compensation with a larger data prescaler)")
            else:
                lines.append(f"  WARNING: every timing below needs a data prescaler above {tdc_max}, and this "
                             f"controller cannot use transmitter delay compensation with those. Use a CAN clock "
                             f"that gives the data bitrate with prescaler 1 or 2.")
        for c in dat[:top]:
            lines.append("  " + fmt(c, sjw))
            lines.append("      " + registers(profile, c, data=True))
        shared = [(n, d) for n in nom for d in dat if n["brp"] == d["brp"]]
        if shared:
            n, d = shared[0]
            lines.append(f"\nRecommended pair (same prescaler in both phases, so TQ does not change at BRS): BRP={n['brp']}")
            lines.append("  nominal: " + fmt(n))
            lines.append("  data:    " + fmt(d))
        else:
            d = dat[0]
            lines.append("\nNo common prescaler for both phases; a quantisation phase error occurs at the bit-rate switch.")
        ssp = d["brp"] * (1 + d["tseg1"])
        lines.append(f"Transmitter delay compensation: enable it for data rates of 2 Mbit/s and above. "
                     f"Put the secondary sample point at the data sample point: about {ssp} clock periods "
                     f"({ssp * 1e9 / clock:.0f} ns) after the measured loop delay. "
                     f"Controllers differ by one TQ in how they count this offset; check the datasheet.")
    return "\n".join(lines), 0


def self_test():
    # MCP2515 @ 16 MHz, 500k, 87.5%: 16 TQ, TSEG1=13, TSEG2=2 -> CNF 0x00/0xAE/0x01
    c = candidates(16e6, 500e3, 0.875, PROFILES["mcp2515"], 2)[0]
    assert (c["brp"], c["ntq"], c["tseg1"], c["tseg2"], c["sjw"]) == (1, 16, 13, 2, 1), c
    assert mcp2515_cnf(c)[:3] == (0x00, 0xAE, 0x01), mcp2515_cnf(c)
    # MCP2515 @ 8 MHz, 500k: 8 TQ, exact
    c = candidates(8e6, 500e3, 0.875, PROFILES["mcp2515"], 2)[0]
    assert (c["brp"], c["ntq"], c["err"]) == (1, 8, 0.0), c
    # MCP2515 @ 8 MHz cannot make 1 Mbit/s with >= 5 TQ... it can make exactly 4 TQ, which is below the 5 TQ minimum
    assert candidates(8e6, 1e6, 0.75, PROFILES["mcp2515"], 2) == []
    # ESP32 TWAI @ 80 MHz 500k 80% reproduces ESP-IDF's TWAI_TIMING_CONFIG_500KBITS (brp 8, tseg 15/4)
    c = candidates(80e6, 500e3, 0.80, PROFILES["twai"])[0]
    assert (c["brp"], c["tseg1"], c["tseg2"]) == (8, 15, 4), c
    # bxCAN @ 42 MHz 500k: 42M / 500k = 84 = 6 * 14 -> exact with BRP 6
    c = candidates(42e6, 500e3, 0.875, PROFILES["bxcan"])[0]
    assert c["err"] == 0.0 and c["brp"] * c["ntq"] == 84, c
    # M_CAN 40 MHz 500k/2M: a shared prescaler exists
    out, rc = report("mcan", 40e6, 500e3, 0.8, 3, 0.0, 2e6, 0.8)
    assert rc == 0 and "Recommended pair" in out, out
    assert parse_num("500k") == 500000 and parse_num("2M") == 2e6 and parse_num("8e6") == 8e6
    # MCP2515: PropSeg + PS1 >= PS2 holds whatever sample point is asked for
    assert all(c["tseg1"] >= c["tseg2"] for c in candidates(8e6, 500e3, 0.40, PROFILES["mcp2515"], 2))
    # a requested SJW is honoured up to PS2 and no further, and the report says when it was cut
    assert candidates(16e6, 500e3, 0.875, PROFILES["mcp2515"], 2, sjw=4)[0]["sjw"] == 2
    assert "--sjw 4 is not possible" in report("mcp2515", 16e6, 500e3, 0.875, 1, 0.0, sjw=4)[0]
    # M_CAN data phase: segment 2 is at least 2 TQ, and at TDC rates only prescalers 1 and 2 are offered
    assert all(c["tseg2"] >= 2 for c in candidates(40e6, 5e6, 0.875, PROFILES["mcan"]["data"]))
    out, rc = report("mcan", 80e6, 500e3, 0.8, 9, 0.0, 2e6, 0.8)
    assert rc == 0 and "DataPrescaler=4" not in out and "DataPrescaler=2" in out, out
    for bad in (["--clock", "8e6", "--bitrate", "0"], ["--clock", "x", "--bitrate", "500k"],
                ["--clock", "8e6", "--bitrate", "500k", "--sample-point", "30"]):
        try:
            import contextlib, io
            with contextlib.redirect_stderr(io.StringIO()):
                main(bad)
            raise AssertionError(f"{bad} should be rejected")
        except SystemExit as e:
            assert e.code == 2, (bad, e.code)
    print("self-test OK")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="generic")
    ap.add_argument("--clock", help="CAN core clock in Hz, e.g. 8e6, 16M, 80000000")
    ap.add_argument("--bitrate", help="nominal bitrate, e.g. 500k")
    ap.add_argument("--sample-point", type=float, help="percent; default 87.5 (<=500k), 80 (<=800k), 75 (above)")
    ap.add_argument("--data-bitrate", help="CAN FD data-phase bitrate, e.g. 2M")
    ap.add_argument("--data-sample-point", type=float, help="percent")
    ap.add_argument("--sjw", type=int, help="ask for this SJW (default: as large as the controller and TSEG2 "
                                            "allow; the output says so if it had to be reduced)")
    ap.add_argument("--max-error", type=float, default=0.0,
                    help="allowed bitrate error in percent (default 0: exact only). Keep it well under 0.5")
    ap.add_argument("--top", type=int, default=3, help="candidates to show (default 3)")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return 0
    if a.list_profiles:
        for name, p in sorted(PROFILES.items()):
            print(f"{name:10} {p['desc']}")
        return 0
    if not a.clock or not a.bitrate:
        ap.error("--clock and --bitrate are required")
    try:
        clock, bitrate = parse_num(a.clock), parse_num(a.bitrate)
        data_bitrate = parse_num(a.data_bitrate) if a.data_bitrate else None
    except ValueError:
        ap.error("--clock, --bitrate and --data-bitrate take numbers such as 8e6, 16M, 500k")
    if clock <= 0 or bitrate <= 0 or (data_bitrate is not None and data_bitrate < bitrate):
        ap.error("the clock and bitrate must be above zero, and the data bitrate not below the nominal bitrate")
    for name, val in (("--sample-point", a.sample_point), ("--data-sample-point", a.data_sample_point)):
        if val is not None and not 50 <= val <= 95:
            ap.error(f"{name} is a percentage between 50 and 95 (typical: 75 to 87.5), got {val:g}")
    if (a.sjw is not None and a.sjw < 1) or a.top < 1 or a.max_error < 0:
        ap.error("--sjw and --top must be at least 1, --max-error not negative")
    sp = a.sample_point / 100 if a.sample_point else default_sample_point(bitrate)
    out, rc = report(a.profile, clock, bitrate, sp, a.top, a.max_error / 100, data_bitrate,
                     a.data_sample_point / 100 if a.data_sample_point else None, a.sjw)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
