# Changelog

## 1.0.0

Initial release.

- `canbus` skill: entry point plus 14 reference files covering the CAN protocol, bit timing, physical layer, controllers, transceivers, OBD-II, UDS/ISO-TP, J1939, CANopen, reverse engineering, tooling, DBC and troubleshooting.
- Scripts: `can_bit_timing.py`, `can_log_analyze.py`, `can_signal_search.py`, `obd_decode.py`, `isotp_decode.py`.
- `assets/template.dbc`.
- Ten eval cases under `evals/`: eight tasks, and two prompts that must not load the skill.
- `tests/test_documented_packages.py`: makes the python-can, cantools, can-isotp, udsoncan and canopen calls shown in the references against simulated devices.
