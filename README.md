# canbus

A skill that gives an AI coding agent (Claude Code, claude.ai, and other agents that support [Agent Skills](https://agentskills.io)) working knowledge of CAN bus: the protocol, vehicle diagnostics, the common chips, and how to reverse engineer an unknown bus.

A skill is a folder of instructions, reference notes and small tools. Once installed, the agent can load it on its own when a conversation is about CAN. If it does not, ask for it by name ("use the canbus skill").

It is written for people building gauges, data loggers, retrofits, test rigs and industrial or vehicle integrations, and for anyone debugging a bus that will not talk.

## What you can ask once it is installed

> My ESP32 with an MCP2515 module prints "init ok" and then receives nothing from my car's OBD port. Here is my wiring and code...

> I recorded baseline.log with nothing happening and door.log where I opened the driver's door three times. Which message and bit is the door?

> drive.log has the car's internal CAN traffic plus OBD-II speed that I polled at the same time. Find the real speed signal and give me a DBC line.

> I need CNF1/CNF2/CNF3 for an MCP2515 with an 8 MHz crystal at 250 kbit/s and an 87.5 % sample point.

> Which transceiver should I use with a 3.3 V STM32 on a CAN FD bus at 2 Mbit/s?

> What do these frames from my truck mean? `18FECA00#04FF6E000301FFFF` ...

Two habits make the answers better:

- **Say what you have**: the controller and transceiver part numbers, the crystal or clock frequency, the bitrate, and what you measured.
- **Point at log files, do not paste them.** A capture is tens of thousands of lines. Give the agent the file path and it will run the bundled tools on it.

## Install

Pick the one line that matches how you use Claude. In the commands below, replace `OWNER/REPO` with this repository's path on GitHub.

### Claude Code (recommended)

```bash
claude plugin marketplace add OWNER/REPO
claude plugin install canbus@canbus-skill
```

Start a new session afterwards. To update later: `claude plugin marketplace update canbus-skill`, then `claude plugin update canbus@canbus-skill`.

### Claude Code, without the plugin system

```bash
git clone https://github.com/OWNER/REPO
mkdir -p ~/.claude/skills
cp -r REPO/skills/canbus ~/.claude/skills/
```

That installs it for all your projects. To install it for one project only, run this from that project's folder instead (give the path to wherever you cloned the repository):

```bash
mkdir -p .claude/skills
cp -r /path/to/REPO/skills/canbus .claude/skills/
```

### claude.ai

```bash
git clone https://github.com/OWNER/REPO
cd REPO/skills
zip -r canbus.zip canbus -x "*/__pycache__/*" "*.DS_Store"
```

Then, in claude.ai:

1. Switch on code execution if it is off: **Settings > Capabilities > Code execution and file creation**. The skill runs Python tools, so it needs this.
2. Go to **Customize > Skills**, click **+**, then **Create skill**, then **Upload a skill**, and choose `canbus.zip`.
3. Make sure the skill is enabled in that list.

On Team and Enterprise plans an owner can switch off user-created skills. Anthropic's guides: [Using skills in Claude](https://support.claude.com/en/articles/12512180-using-skills-in-claude) and [How to create custom skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills).

### Other agents that support Agent Skills

```bash
npx skills add OWNER/REPO --list            # see what the repository offers, installs nothing
npx skills add OWNER/REPO --skill canbus
```

This uses the open-source [`skills` installer](https://github.com/vercel-labs/skills) and needs Node.js. The agent must support Agent Skills and be able to run Python scripts; the installer's own documentation lists the agents it knows. Without Node.js, copy the `skills/canbus` folder into the directory your agent reads skills from.

### Check that it loaded

Ask the agent "which CAN bus skill do you have?". In Claude Code you can also type `/` and look for it in the list: it appears as `canbus:canbus` when installed as a plugin and as `canbus` when copied in by hand.

## Requirements

- **Python 3.8 or newer** for the bundled tools. Nothing to `pip install`: they use only the standard library. On Windows, use `python` where the examples say `python3`.
- Nothing else for analysing saved logs, on any operating system.
- For talking to a live bus you need a CAN interface, and on Linux the `can-utils` package. The skill explains which interface to buy and how to set it up, and suggests Python packages (python-can, cantools) when a task needs them.

## What it covers

| Area | Contents |
|---|---|
| Protocol | Classical CAN, CAN FD, CAN XL overview: frames, arbitration, error handling, bus-off behaviour |
| Bit timing | Sample points, register values for common controllers, CAN FD data phase |
| Physical layer | Termination, wiring, connector pinouts (OBD-II, DB9, M12, Deutsch), scope and meter checks |
| Controllers | MCP2515, MCP2517FD/MCP2518FD, TCAN4550, SJA1000, ESP32 TWAI (both ESP-IDF drivers), STM32 bxCAN and FDCAN, Teensy, RP2040, Raspberry Pi HATs |
| Transceivers | SN65HVD23x, TCAN33x, TJA1050/1051/1042/1043/1044, TCAN1042/1051, MCP2551/2561/2562(FD), isolated parts, selection rules |
| Diagnostics | OBD-II services, PIDs, trouble codes, readiness monitors, ELM327 adapters; ISO-TP; UDS services, error codes, sessions, ECU discovery |
| Other protocols | SAE J1939, NMEA 2000, CANopen (incl. CiA 402), brief notes on DeviceNet, DroneCAN, XCP |
| Reverse engineering | Capture, inventory, diffing, searching against a reference, scaling, counters and checksums, writing a DBC file |
| Tooling | SocketCAN, can-utils, python-can, cantools, SavvyCAN, interfaces, log formats |
| Troubleshooting | Symptom-to-cause tables for a bus that does not work |

## The bundled tools

The agent runs these for you, and they also work by themselves from a clone of this repository:

| Script | What it does | Example arguments (the log files are your own) |
|---|---|---|
| `can_bit_timing.py` | Bit-timing and register values for a controller and clock | `--profile mcp2515 --clock 8e6 --bitrate 500k` |
| `can_log_analyze.py` | Lists every message in a capture with its rate and byte behaviour; shows what changed between two captures | `baseline.log --diff action.log` |
| `can_signal_search.py` | Finds the signal that follows a known value (for example OBD-II speed in the same capture), with scale and offset | `drive.log --obd-pid 0D` |
| `obd_decode.py` | Decodes OBD-II requests and responses | `41 0C 1A F8` |
| `isotp_decode.py` | Rebuilds multi-frame diagnostic messages and labels them | `capture.log` |

```bash
cd REPO
python3 skills/canbus/scripts/can_log_analyze.py baseline.log --diff action.log
python3 skills/canbus/scripts/can_bit_timing.py --help          # every script has --help
```

Replace `baseline.log` and `action.log` with your own captures. The tools read candump logs (`candump -l`), candump screen output, plain `123#DEADBEEF` lines, and SavvyCAN CSV.

They are built not to guess. A file recorded from two interfaces is refused until you pick one with `--bus`. A diagnostic reply that is cut short is reported as malformed, not decoded. A signal found by `can_signal_search.py` is called a candidate until `--check` confirms it on a second capture. A non-zero exit status means the tool could not give a sound answer.

## Safety

CAN buses control physical machinery. The skill instructs the agent to sniff in listen-only mode, to keep injection and fuzzing off moving vehicles, to explain the consequences of any diagnostic request that changes something before giving it, and to decline help with defeating immobilisers, odometers, emissions controls or safety systems. Use it on equipment you own or are authorised to test.

## Accuracy and limits

- Standardised material (frame formats, OBD-II PIDs, UDS services, J1939 and CANopen basics) is stated directly.
- Chip figures are headline values for choosing a part. Confirm electrical limits against the current datasheet.
- Manufacturer-specific CAN IDs, signal layouts and diagnostic identifiers are deliberately not included. The skill explains how to find and verify them for your vehicle.
- The tools have been tested on generated captures and simulated devices, not yet on a wide range of real vehicles. Treat a decoded signal as a hypothesis until you have checked it on a second capture; the tools help you do that.

## Repository layout

```
.claude-plugin/        plugin and marketplace manifests
skills/canbus/
  SKILL.md             entry point the agent reads first
  references/          14 topic files, read only when needed
  scripts/             the 5 Python tools
  assets/template.dbc  a valid DBC file to start from
evals/                 test tasks with pass criteria, and two prompts that must not load the skill
tests/                 exercises the third-party-package calls the references show
```

## Contributing

Corrections are welcome, especially from real hardware. Before sending a change, run:

```bash
for s in skills/canbus/scripts/*.py; do python3 "$s" --self-test; done
claude plugin validate . --strict                                  # the plugin and its skill
claude plugin validate .claude-plugin/marketplace.json --strict    # the marketplace listing
```

The references also show code for third-party packages (python-can, cantools, can-isotp, udsoncan, canopen). `tests/test_documented_packages.py` makes the same calls against simulated devices, with no hardware. It is a hand-kept copy of those calls, so change both together. To reproduce the versions it was last run with:

```bash
python3 -m venv .venv
.venv/bin/pip install python-can==4.6.1 cantools==45.2.0 can-isotp==2.0.7 udsoncan==1.26.1 canopen==2.4.1
.venv/bin/python tests/test_documented_packages.py
```

Drop the version pins to test against current releases, and update the table in `skills/canbus/references/tools.md` if a newer one needs a change.

The cases in `evals/` run with Claude Code 2.1.269 or later:

```bash
claude plugin eval . --scaffold --allow-tools Bash Write Edit
```

- These are real, billed model runs: by default three per case, with the skill and without it.
- `--scaffold` copies each case's capture files into place. It runs the `place-files.sh` scripts from this repository on your machine, so read them first.
- `--allow-tools` lets the agent run the bundled Python tools. Without it the file-based cases cannot work, whatever the case files list.
- The first run asks whether you trust the plugin directory.

**Releasing.** The version is written in three places that must match: `.claude-plugin/plugin.json`, `metadata.version` in `skills/canbus/SKILL.md`, and the newest heading in `CHANGELOG.md`. Installed copies only update when the plugin version changes, so bump it for every release.

## Acknowledgements

The reference-driven signal search (find a field by correlating it with an OBD-II PID or another known value, then check the result on a second capture) follows ideas from CSS Electronics' MIT-licensed [can-bus-reverse-engineering-skills](https://github.com/CSS-Electronics/can-bus-reverse-engineering-skills) and their article [CAN bus reverse engineering with AI](https://www.csselectronics.com/pages/can-bus-reverse-engineering-ai-llm-claude). The implementation here is independent and works with any interface and log format.

## Licence

MIT. See [LICENSE](LICENSE).
