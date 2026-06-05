# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

SKKU senior capstone — a fire-safety oriented "heat algorithm" prototype aligned with [ksk192830/CapstoneDesign](https://github.com/ksk192830/CapstoneDesign). An ESP32-P4 robot streams RGB + thermal over WiFi; a laptop classifies materials at heat hotspots (HuggingFace `prithivMLmods/Minc-Materials-23`), cross-references `재료별_불연성_가연성_발화점_참고표.xlsx` for ignition-point / fire-risk scoring, raises a trend-based ignition early-warning, and serves a **single browser interface**: two camera feeds on top, drive control on the bottom.

## Repository layout

```
docs/                          # architecture, hardware, protocol
  superpowers/specs/, plans/   # design specs + implementation plans
shared/                        # WebSocket JSON schema + examples (future control transport)
firmware/
  esp32-p4/                    # FULL firmware: camera + thermal + omni-wheel MOTOR control
  esp32-p4-unified/            # camera + thermal only (no motors)
laptop/                        # Cross-platform Python client (macOS / Windows / Linux)
  pyproject.toml
  src/machine_vision_client/
    main.py                    # ★ orchestrator: capture loop + web app + motor client
    heat_algorithm.py          # back-compat shim -> main()
    config.py                  # ESP32_HOST / MOTOR_HOST, endpoint URLs, LOCAL_DEV
    materials.py, risk.py, thermal.py, ignition_warning.py
    vision/pipeline.py         # VisionPipeline + InferenceWorker (ViT classification)
    video/                     # visible_stream.py, thermal_stream.py (sources)
    ui/                        # web_server.py (Flask), debug_viewer.py, templates/index.html
    control/                   # motor_http.py (MotorHttpClient); comms/ stub (future WS)
  tests/
heat_algorithm                 # Root launcher -> machine_vision_client.main
SETUP.md                       # full flashing / WiFi-change walkthrough
```

## Running

The app serves a **browser web UI** (Flask MJPEG), not OpenCV windows.

```bash
# Install laptop package (once)
.venv/bin/python -m pip install -e laptop/

# Run against the car (board IP on the LAN)
ESP32_HOST=<board-ip> .venv/bin/python heat_algorithm

# Local dev — webcam + mock thermal, no board
HEAT_LOCAL=1 .venv/bin/python heat_algorithm
```

Then open **http://localhost:8000**. Stop with **Ctrl-C**.
Drive (click the page first for keyboard focus): **W A S D** move, **Q E** rotate, on-screen **joystick**, **Space**/**STOP** to halt. Live-tune classification with the grid `+/-` and min-conf buttons.

### venv shebang note

The venv may have stale shebangs if the directory was renamed. Always invoke via `.venv/bin/python -m pip …`, not bare `pip`.

## Firmware & connecting to the car

Two firmware trees serve the **same HTTP contract** but on **swapped ports** — `config.py` is currently set for **`esp32-p4`**:

| Firmware | camera `/stream.mjpg` | thermal `/thermal/frame` | motor `/control/*` |
|---|---|---|---|
| `esp32-p4` (full)        | **:81** | **:80** | **:80** |
| `esp32-p4-unified`       | :80 | :81 | — (none) |

**WiFi credentials:** `firmware/*/src/network/wifi_credentials.h` is **git-ignored** (real passwords must never be committed — `origin` is the public upstream). Edit it locally; the ESP32 only learns a network when reflashed.

**Flash** (board on USB, e.g. `/dev/cu.usbmodem3101`):
```bash
cd firmware/esp32-p4 && pio run -t upload --upload-port /dev/cu.usbmodem3101
```

**Find the board IP** (USB serial drops at runtime, so don't rely on the monitor): the board joins the LAN as a DHCP client. Scan the subnet and probe `:80/` for the firmware signature (`/control/manual`, `/stream.mjpg`), or check the router. Then `export ESP32_HOST=<ip>`. Verify: `curl --max-time 3 http://<ip>:81/stream.mjpg` (camera), `http://<ip>/thermal/frame` (thermal), `http://<ip>/control/status` (motors).

See `SETUP.md` for the full step-by-step.

## Architecture notes

`main.py` loop (per frame): read RGB (`video/visible_stream.py`) + thermal (`video/thermal_stream.py`) → `detect_hotspot` → submit to `vision/pipeline.py` (async ViT grid + hotspot classification, CUDA→MPS→CPU) → update `risk.py` score + `ignition_warning.py` monitor → `ui/debug_viewer.py` draws HUD + ignition overlay → `ui/web_server.py` publishes two MJPEG feeds. Drive commands flow browser → `POST /control/drive` → `control/motor_http.MotorHttpClient.set_vector` → ESP32 `/control/manual` (its background thread handles the TTL deadman + auto-stop).

- **Shared TTI physics** lives in `risk.py` (`fit_rate_c_per_s` least-squares slope + `estimate_tti`); both `RiskState` and the ignition monitor use it. AIT lookup is `materials.ignition_threshold_c`.
- **Ignition alert** (`IgnitionTrendMonitor`) is a pure state machine; all its OpenCV drawing is in `debug_viewer.draw_ignition_overlay` (UI layer).
- **Network resilience:** `VisibleStream.read()` never raises and the main loop retries a network source indefinitely, so a board reboot/WiFi blip pauses (shows "Waiting for stream…") and auto-reconnects instead of crashing.

Tuning knobs (constants): `PREDICT_EVERY_N_FRAMES`, `HOTSPOT_THRESHOLD_C` (`vision/pipeline.py`); thermal alignment (`THERMAL_ROTATE_*`, `THERMAL_CROP_*`) and `ARM_THRESHOLD_C`/`HORIZON_S` (`ignition_warning.py`). Override the board with `ESP32_HOST` (and `MOTOR_HOST` if motors are on a different board).

When extending toward full CapstoneDesign integration, wire `comms/esp32_client.py` against `shared/protocol/` and `docs/protocol.md` (WebSocket control is currently out of scope; HTTP `/control/manual` is the transport).
