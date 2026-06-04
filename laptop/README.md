# Laptop Client

Laptop-side application for receiving ESP32-P4 camera/thermal streams, running
the fire-risk heat algorithm, and (future) sending control commands back.

Cross-platform: macOS, Windows, and Linux. See repo-root `SETUP.md` for
platform-specific serial-port and venv notes.

## Setup

From the repo root, install dependencies into a venv:

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -e laptop/

# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e laptop/
```

## Run the heat algorithm

From the `laptop` directory (with `src` on the module path via editable install):

```bash
# macOS / Linux — ESP32 on Wi-Fi (default ESP32_HOST in config.py)
../.venv/bin/python -m machine_vision_client.main

# Local dev — webcam + mock thermal, no board
HEAT_LOCAL=1 ../.venv/bin/python -m machine_vision_client.main

# Windows
set HEAT_LOCAL=1
..\.venv\Scripts\python.exe -m machine_vision_client.main
```

Or from the repo root via the legacy launcher:

```bash
.venv/bin/python heat_algorithm
```

Press `q` in the RGB window to quit.

## Configuration

Edit `src/machine_vision_client/config.py`, or set environment variables:

| Variable | Purpose |
|---|---|
| `ESP32_HOST` | Board IP on the LAN (default `172.20.10.8`) |
| `HEAT_LOCAL=1` | Webcam index 0 + mock thermal |
| `THERMAL_PORT` | USB serial port override (`COM3`, `/dev/cu.usbmodem3101`, …) |

Protocol and architecture docs live in `../docs/` and `../shared/`.
