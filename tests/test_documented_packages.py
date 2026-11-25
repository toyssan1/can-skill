#!/usr/bin/env python3
"""Runs the third-party-package code shown in skills/canbus/references against simulated devices.

No hardware: everything uses python-can's `virtual` interface. Run it after editing a snippet in the
references, or when a package releases a new major version.

    python3 -m venv .venv && .venv/bin/pip install python-can cantools can-isotp udsoncan canopen
    .venv/bin/python tests/test_documented_packages.py
"""
import os
import sys
import tempfile
import threading
import time

try:
    import can
    import canopen
    import cantools
    import isotp
    import udsoncan
    from udsoncan.client import Client
    from udsoncan.connections import PythonIsoTpConnection
except ImportError as e:
    sys.exit(f"missing package ({e.name}): pip install python-can cantools can-isotp udsoncan canopen")

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "skills", "canbus", "assets", "template.dbc")


def test_python_can():
    """tools.md 'python-can' and obd2.md 'Talking OBD-II directly on CAN'."""
    a, b = can.Bus(interface="virtual", channel="t"), can.Bus(interface="virtual", channel="t")
    assert can.Message(arbitration_id=0x123).is_extended_id is True      # why the docs say: always pass it
    b.set_filters([{"can_id": 0x7E8, "can_mask": 0x7F8, "extended": False}])
    a.send(can.Message(arbitration_id=0x123, data=[1, 2, 3], is_extended_id=False))
    a.send(can.Message(arbitration_id=0x7E8, is_extended_id=False, data=[0x04, 0x41, 0x0C, 0x1A, 0xF8, 0, 0, 0]))
    msg = b.recv(timeout=1.0)
    assert msg.arbitration_id == 0x7E8 and (msg.data[3] * 256 + msg.data[4]) / 4 == 1726.0
    assert b.recv(timeout=0.05) is None
    for field in ("timestamp", "dlc", "channel", "is_remote_frame", "is_error_frame", "is_fd", "bitrate_switch",
                  "error_state_indicator", "is_rx"):
        assert hasattr(msg, field), field
    b.set_filters(None)
    task = a.send_periodic(can.Message(arbitration_id=0x200, data=[0] * 8, is_extended_id=False), 0.02)
    time.sleep(0.15)
    task.stop()
    seen = 0
    while b.recv(timeout=0.05):
        seen += 1
    assert seen >= 4, seen
    d = tempfile.mkdtemp()
    notifier = can.Notifier(b, [can.Logger(os.path.join(d, "capture.blf"))])
    for i in range(5):
        a.send(can.Message(arbitration_id=0x321, data=[i], is_extended_id=False))
    time.sleep(0.3)
    notifier.stop()
    for src, dst in (("capture.blf", "out.log"), ("out.log", "out.asc"), ("out.asc", "out.trc")):
        with can.LogReader(os.path.join(d, src)) as reader, can.Logger(os.path.join(d, dst)) as writer:
            assert sum(1 for m in reader if writer(m) is None) == 5, (src, dst)
    # the bundled scripts must read what python-can writes
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "canbus", "scripts"))
    from can_log_analyze import read_frames
    assert [f.can_id for f in read_frames(os.path.join(d, "out.log"))] == [0x321] * 5
    a.shutdown()
    b.shutdown()


def test_cantools():
    """tools.md 'cantools' and dbc.md."""
    db = cantools.database.load_file(TEMPLATE)
    assert db.decode_message(201, bytes.fromhex("0BB8405A05000099"))["EngineSpeed"] == 750.0
    assert db.decode_message(947, bytes([0x40, 0x04, 0x03, 0xF0])) == \
        {"DriverDoorOpen": "open", "GearSelected": "D", "SteeringAngle": -24.0}
    assert db.decode_message(0x18FEEEFE, bytes([0x6E] + [0xFF] * 7))["EngineCoolantTemp"] == 70
    try:
        db.decode_message(0x999, b"\x00")
        raise AssertionError("unknown ID should raise KeyError")
    except KeyError:
        pass
    frame = db.get_message_by_name("ENGINE_1")
    data = frame.encode({"EngineSpeed": 1500, "ThrottlePos": 10, "CoolantTemp": 90, "Counter": 0, "Checksum": 0})
    assert (frame.frame_id, frame.is_extended_frame, data[:2].hex()) == (201, False, "1770")


def test_uds():
    """uds.md 'UDS with python', against a simulated ECU with a multi-frame VIN."""
    stop = threading.Event()

    def ecu():
        bus = can.Bus(interface="virtual", channel="uds")
        stack = isotp.CanStack(bus=bus, params={"tx_padding": 0xAA},
                               address=isotp.Address(isotp.AddressingMode.Normal_11bits, txid=0x7E8, rxid=0x7E0))
        stack.start()
        while not stop.is_set():
            req = stack.recv(block=True, timeout=0.1)
            if not req:
                continue
            if req[:3] == bytes.fromhex("22F190"):
                stack.send(bytes.fromhex("62F190") + b"W0L000043MB541326")
            elif req[:2] == bytes.fromhex("1003"):
                stack.send(bytes.fromhex("5003003201F4"))
            elif req[:2] == bytes.fromhex("1902"):
                stack.send(bytes.fromhex("5902FF" "01331109" "C1000008"))
            else:
                stack.send(bytes([0x7F, req[0], 0x11]))
        stack.stop()
        bus.shutdown()

    threading.Thread(target=ecu, daemon=True).start()
    time.sleep(0.2)
    bus = can.Bus(interface="virtual", channel="uds")
    addr = isotp.Address(isotp.AddressingMode.Normal_11bits, txid=0x7E0, rxid=0x7E8)
    stack = isotp.NotifierBasedCanStack(bus=bus, notifier=can.Notifier(bus, []), address=addr,
                                        params={"tx_padding": 0xAA})
    cfg = dict(udsoncan.configs.default_client_config)
    cfg["data_identifiers"] = {0xF190: udsoncan.AsciiCodec(17)}
    try:
        with Client(PythonIsoTpConnection(stack), config=cfg, request_timeout=2) as client:
            assert client.read_data_by_identifier(0xF190).service_data.values[0xF190] == "W0L000043MB541326"
            client.change_session(3)
            dtcs = [f"{d.id:06X} status {d.status.get_byte_as_int():02X}"
                    for d in client.get_dtc_by_status_mask(0x08).service_data.dtcs]
            assert dtcs == ["013311 status 09", "C10000 status 08"], dtcs
    finally:
        stop.set()
        time.sleep(0.3)


def test_canopen():
    """canopen.md 'Tooling', against a simulated node."""
    od = canopen.ObjectDictionary()
    var = canopen.objectdictionary.ODVariable("Device type", 0x1000)
    var.data_type, var.access_type, var.default = canopen.objectdictionary.UNSIGNED32, "ro", 0x00020192
    od.add_object(var)
    net, sim = canopen.Network(), canopen.Network()
    net.connect(interface="virtual", channel="co")
    sim.connect(interface="virtual", channel="co")
    local = canopen.LocalNode(5, od)
    sim.add_node(local)
    node = canopen.RemoteNode(5, od)
    net.add_node(node)
    assert node.sdo[0x1000].raw == 0x00020192
    node.nmt.state = "OPERATIONAL"
    time.sleep(0.1)
    assert local.nmt.state == "OPERATIONAL"
    assert hasattr(node.tpdo, "read") and hasattr(net, "scanner")
    net.disconnect()
    sim.disconnect()


if __name__ == "__main__":
    for test in (test_python_can, test_cantools, test_uds, test_canopen):
        test()
        print("ok  ", test.__name__, "-", test.__doc__.strip().splitlines()[0])
    print("versions:", ", ".join(f"{m.__name__} {m.__version__}" for m in (can, cantools, isotp, udsoncan, canopen)))
