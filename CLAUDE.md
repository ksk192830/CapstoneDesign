# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

SKKU senior capstone — a fire-safety oriented "heat algorithm" prototype aligned with [ksk192830/CapstoneDesign](https://github.com/ksk192830/CapstoneDesign). Real-time material classification from RGB + thermal feeds using HuggingFace `prithivMLmods/Minc-Materials-23`, cross-referenced against `재료별_불연성_가연성_발화점_참고표.xlsx` for ignition-point / fire-risk scoring.

## Repository layout

```
docs/                          # architecture, hardware, protocol (from CapstoneDesign)
shared/                        # WebSocket JSON schema + examples
firmware/esp32-p4-unified/     # Unified ESP32-P4 firmware (camera + thermal)
laptop/                        # Cross-platform Python client (macOS / Windows / Linux)
  pyproject.toml
  src/machine_vision_client/
    heat_algorithm.py          # Main RGB + thermal → material → risk loop
    materials.py, risk.py, thermal.py
    config.py                  # ESP32_HOST, LOCAL_DEV, platform serial defaults
    comms/, control/, video/, vision/, ui/   # CapstoneDesign stubs (future integration)
  tests/
heat_algorithm                 # Root launcher → machine_vision_client.main
```

## Running

```bash
# Install laptop package (once)
.venv/bin/python -m pip install -e laptop/

# Heat algorithm (ESP32 on Wi-Fi)
.venv/bin/python heat_algorithm
# or: cd laptop && ../.venv/bin/python -m machine_vision_client.main

# Local dev — webcam + mock thermal
HEAT_LOCAL=1 .venv/bin/python heat_algorithm
```

Press `q` in the OpenCV RGB window to quit.

### venv shebang note

The venv may have stale shebangs if the directory was renamed. Always invoke via `.venv/bin/python -m pip …`, not bare `pip`.

## Architecture notes

`heat_algorithm.py` pipeline:

1. **`load_model()`** — ViT via transformers; device CUDA → MPS → CPU.
2. **`InferenceWorker`** — background thread for grid + hotspot classification so display stays live.
3. **Thermal alignment** — `THERMAL_ROTATE_CCW`, `THERMAL_MIRROR_H`, `THERMAL_CROP_*` in `heat_algorithm.py`; projection via `thermal.project_thermal_to_rgb`.
4. **Sources** — `config.py`: HTTP MJPEG/JPEG from ESP32 (`RGB_SOURCE`, `THERMAL_HTTP_URL`) or USB serial / mock.

Tuning knobs: `PREDICT_EVERY_N_FRAMES`, `HOTSPOT_THRESHOLD_C`, patch-grid density (`+`/`-` keys), `PATCH_MIN_CONFIDENCE` (`,`/`.` keys). Override board IP with `ESP32_HOST` env var.

When extending toward full CapstoneDesign integration, wire `comms/esp32_client.py` and `control/controller.py` against `shared/protocol/` and `docs/protocol.md`.
