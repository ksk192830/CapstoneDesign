# Heat Algorithm Integration — Design

**Date:** 2026-06-04
**Status:** Approved (design); pending implementation plan
**Source of truth:** [`ksk192830/CapstoneDesign`](https://github.com/ksk192830/CapstoneDesign) laptop client module layout

## Goal

Integrate the working heat algorithm (RGB + thermal → material classification →
fire-risk scoring → on-screen HUD) into CapstoneDesign's `machine_vision_client`
package by **decomposing the existing `heat_algorithm.py` monolith into the
package's already-defined module slots**, so the result follows CapstoneDesign's
conventions and is PR-ready.

The deliverable is a **standalone heat video feed**: two OpenCV windows (RGB with
material/risk HUD, thermal view). No interaction with car motor control.

## Context

CapstoneDesign's `machine_vision_client` defines a clean module layout, but only
`video/visible_stream.py` is implemented. `video/thermal_stream.py`,
`vision/pipeline.py`, `ui/debug_viewer.py` are empty `class X: pass` stubs — i.e.
labeled slots. All the real heat logic currently lives crammed in a single
~885-line `heat_algorithm.py` (the mature version on the local `ethan` /
`merge/main-ethan` branch, which has the background `InferenceWorker` and
thermal→RGB projection). This design moves each responsibility into its slot.

The more mature local `heat_algorithm.py` is the source content, **not** the older
25 KB copy that exists upstream.

## Non-goals (explicitly out of scope this pass)

- Car motor control: `control/motor_http.py`, `control/drive_panel.py`, the
  `FIRMWARE_PROFILE` / `CAR_CONTROL` config, and the DrivePanel hooks added in
  commit `8487332`. Heat must not import or depend on any of these.
- The dead WebSocket control contract (`CONTROL_WS_URL`, `comms/esp32_client.py`,
  `comms/protocol.py`). Left untouched.
- Any heat → control signalling (e.g. fire-risk stop/alert). Confirmed independent.

## Architecture — module map

| Target slot | Public class | Absorbs from `heat_algorithm.py` |
|---|---|---|
| `video/visible_stream.py` (extend existing) | `VisibleStream` | `HttpJpegSource`, `open_rgb_capture`, `make_error_frame`. One class handles webcam-index / `.mjpg` stream / `.jpg`-poll sources behind `.open()/.read()/.release()`. |
| `video/thermal_stream.py` (fill stub) | `ThermalStream` | thermal source selection (HTTP → USB serial → mock), the `THERMAL_ROTATE_CCW / MIRROR_H / CROP_*` alignment constants, `rotate_thermal_frame`, and the `EFF_THERMAL_*` derivation. Exposes `.read() -> ThermalFrame`. |
| `vision/pipeline.py` (fill stub) | `VisionPipeline` | `load_model`, `classify_top1`, `classify_patches`, `aggregate_patches`, `crop_around`, projection (`_proj_kwargs`, `EFF_THERMAL_*` use), `grid_for_density`, the full `InferenceWorker` + `_InferJob` / `_InferResult`, and ownership of `RiskState`. |
| `ui/debug_viewer.py` (fill stub) | `DebugViewer` | `draw_regions`, `_region_color`, `draw_hud`, `risk_color_bgr`, `format_status`, `_font_scale_for_cell`, `render_thermal_view` wiring, window-name constants. |
| `main.py` (thin orchestrator) | `main()` | the display loop: read both sources → submit to pipeline every N frames → take result → viewer draws two windows → handle keys (`q`/Esc quit, `+`/`-` density, `,`/`.` min-confidence) → FPS. |
| `config.py` | — | reconcile stream/thermal URLs to the firmware the board actually serves; keep `LOCAL_DEV`, `RGB_SOURCE`, `THERMAL_HTTP_URL`, `THERMAL_PORT`, `THERMAL_BAUD`, `RGB_W/H`; **drop** car-control keys. |
| `heat_algorithm.py` | — | deleted, or reduced to a 2-line shim re-exporting `main` for back-compat. |

## Interfaces

```
VisibleStream(url_or_index).open() / .read() -> frame | None / .release()
ThermalStream().read() -> ThermalFrame          # rotation + crop applied internally
VisionPipeline(materials)
    .submit(frame, tframe, cols, rows, min_conf) # enqueue latest job (drops stale)
    .try_take_result() -> InferResult | None     # background ViT thread result
    .bump_generation()                           # invalidate on grid change
    .risk -> RiskState                           # read-only, for HUD
    .stop()
DebugViewer
    .render_rgb(frame, result, risk, fps) -> None
    .render_thermal(tframe, live_hotspot) -> None
```

Each unit is testable in isolation:
- `ThermalStream`: mock/fixture frame → assert rotation/crop dims + FOV.
- `VisionPipeline`: fixture image + synthetic `ThermalFrame` → returns regions and
  produces a `RiskState` update. No camera or board required.
- `DebugViewer`: canned `InferResult` → renders without error.

## Data flow

```
VisibleStream.read ─┐
                    ├─> main loop ──(every PREDICT_EVERY_N_FRAMES)──> VisionPipeline.submit
ThermalStream.read ─┘                                                      │
                                                                  [ViT background thread]
                                                                          │ risk.update
                          DebugViewer <── try_take_result <───────────────┘
                          │
                          └─> 2 OpenCV windows (RGB + HUD, thermal)
```

Behavior is unchanged; responsibilities are relocated. The background-inference
threading model (latest-job-only queue, generation counter, result lock) moves
intact into `VisionPipeline`. The `RiskState` lock stays internal to the pipeline;
`DebugViewer` only reads `risk`.

## Config & endpoint reconciliation

CapstoneDesign's `config.py` points at `/stream/visible.mjpeg` and `/thermal/frame`;
the actual ESP32 firmware serves `/stream.mjpg` (thermal on `:81` for the unified
board). `config.py` will be set to match the firmware the board actually runs, with
`ESP32_HOST` and `HEAT_LOCAL=1` (webcam + mock thermal) env overrides preserved.
**Live URLs to be confirmed against the running board at implementation time.**

## Error handling (preserved from current behavior)

- RGB source stall: show "Waiting for stream…" error frame, reopen after N
  consecutive failures (network sources only).
- Thermal source unreachable: fall back to `MockThermalSource` with a log line.
- Hotspot projected outside RGB view: label as out-of-view, skip classification.

## Testing

- Extend existing `tests/` (already has `test_http_thermal_source.py`).
- Add `VisionPipeline` fixture-image test (regions returned + risk updated).
- Add `ThermalStream` rotation/crop dimension test.
- Manual `HEAT_LOCAL=1` smoke run: two windows, HUD renders, `q`/Esc quits cleanly.
- **Parity check:** confirm decomposed pipeline behaves identically to the monolith
  on the same input before deleting `heat_algorithm.py`.

## Risks

- The background-inference threading is the one delicate extraction; the parity
  check gates the monolith deletion.
- Endpoint drift between `config.py` and firmware must be verified live, not assumed.
