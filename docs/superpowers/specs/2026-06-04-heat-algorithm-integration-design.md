# Heat Algorithm Integration — Design

**Date:** 2026-06-04
**Status:** Approved (design, revised for web interface); pending implementation plan
**Source of truth:** [`ksk192830/CapstoneDesign`](https://github.com/ksk192830/CapstoneDesign) laptop client module layout

## Goal

Integrate the working heat algorithm (RGB + thermal → material classification →
fire-risk scoring → on-screen HUD) into CapstoneDesign's `machine_vision_client`
package by **decomposing the existing `heat_algorithm.py` monolith into the
package's already-defined module slots**, and deliver it as a **browser-based web
interface** served from the laptop.

The deliverable is **two live video feeds in a browser page**:
1. the normal RGB camera **with the heat algorithm drawn on it** (material grid +
   risk HUD + hotspot crosshair), and
2. the **cropped thermal** camera view.

Viewable from any device on the same network (laptop, phone, tablet), like the
firmware's existing browser control page. No interaction with car motor control.

## Context

CapstoneDesign's `machine_vision_client` defines a clean module layout, but only
`video/visible_stream.py` is implemented. `video/thermal_stream.py`,
`vision/pipeline.py`, `ui/debug_viewer.py` are empty `class X: pass` stubs — i.e.
labeled slots. All the real heat logic currently lives crammed in a single
~885-line `heat_algorithm.py` (the mature local `merge/main-ethan` version, with
the background `InferenceWorker` and thermal→RGB projection). This design moves
each responsibility into its slot and replaces the OpenCV windows with a web feed.

The more mature local `heat_algorithm.py` is the source content, **not** the older
25 KB copy that exists upstream.

## Why a web interface (and its hard constraint)

The heat overlay is produced by a PyTorch ViT model that **only runs on the
laptop** — the ESP32 cannot run it. So even in a browser, annotated frames must be
rendered laptop-side. The web interface therefore means: the laptop runs the model
**and** a small web server that streams the annotated RGB + thermal frames as
MJPEG; browsers just display them. This mirrors the "open a browser" feel of the
car's firmware joystick page, but the video is computed on the laptop.

## Non-goals (explicitly out of scope this pass)

- Car motor control: `control/motor_http.py`, `control/drive_panel.py`, the
  `FIRMWARE_PROFILE` / `CAR_CONTROL` config, and the DrivePanel hooks added in
  commit `8487332`. Heat must not import or depend on any of these. Control lives
  in the firmware (`/control/manual` + embedded JS) and, optionally, the local
  Python drive panel — neither is touched here.
- The dead WebSocket control contract (`CONTROL_WS_URL`, `comms/esp32_client.py`,
  `comms/protocol.py`). Left untouched.
- Any heat → control signalling (fire-risk stop/alert). Confirmed independent.
- Embedding the heat feed *into the firmware's* page. The heat page is served
  separately by the laptop; linking the two pages is a future nicety, not in scope.

## Architecture — module map

| Target slot | Public class | Absorbs from `heat_algorithm.py` |
|---|---|---|
| `video/visible_stream.py` (extend existing) | `VisibleStream` | `HttpJpegSource`, `open_rgb_capture`, `make_error_frame`. One class handles webcam-index / `.mjpg` stream / `.jpg`-poll sources behind `.open()/.read()/.release()`. |
| `video/thermal_stream.py` (fill stub) | `ThermalStream` | thermal source selection (HTTP → USB serial → mock), the `THERMAL_ROTATE_CCW / MIRROR_H / CROP_*` alignment constants, `rotate_thermal_frame`, and the `EFF_THERMAL_*` derivation. Exposes `.read() -> ThermalFrame`. |
| `vision/pipeline.py` (fill stub) | `VisionPipeline` | `load_model`, `classify_top1`, `classify_patches`, `aggregate_patches`, `crop_around`, projection (`_proj_kwargs`), `grid_for_density`, the full `InferenceWorker` + `_InferJob` / `_InferResult`, ownership of `RiskState`. Exposes live-tunable `density` / `min_conf`. |
| `ui/debug_viewer.py` (fill stub) | `DebugViewer` | all OpenCV **drawing** only: `draw_regions`, `_region_color`, `draw_hud`, `risk_color_bgr`, `format_status`, `_font_scale_for_cell`, `render_thermal_view` wiring. **Returns annotated `np.ndarray` frames — no `imshow`.** |
| `ui/web_server.py` (new) | `HeatWebServer`, `FrameBus` | Flask app + a thread-safe latest-frame holder. Routes: `/` (HTML page, two `<img>`), `/rgb.mjpg`, `/thermal.mjpg` (MJPEG multipart), `/control/density`, `/control/min_conf` (POST, live tuning). Runs in a daemon thread. |
| `main.py` (thin orchestrator) | `main()` | the loop: read both sources → submit to pipeline every N frames → take result → `DebugViewer` annotates both frames → JPEG-encode → publish to `FrameBus`. Starts `HeatWebServer`. No OpenCV windows. |
| `config.py` | — | reconcile stream/thermal URLs to firmware reality; keep `LOCAL_DEV`, `RGB_SOURCE`, `THERMAL_*`, `RGB_W/H`; add `WEB_HOST`, `WEB_PORT`; **drop** car-control keys (`FIRMWARE_PROFILE`, `CAR_CONTROL`, `MOTOR_BASE_URL`). |
| `heat_algorithm.py` | — | deleted, or reduced to a 2-line shim re-exporting `main`. |
| `pyproject.toml` | — | add `flask` dependency. |

## Interfaces

```
VisibleStream(url_or_index).open() / .read() -> frame|None / .release()
ThermalStream().read() -> ThermalFrame              # rotation + crop applied internally

VisionPipeline(materials)
    .submit(frame, tframe, cols, rows, min_conf)    # enqueue latest job (drops stale)
    .try_take_result() -> InferResult | None        # background ViT thread result
    .bump_generation()                              # invalidate on grid change
    .risk -> RiskState                              # read-only, for HUD

DebugViewer
    .annotate_rgb(frame, result, risk, fps) -> np.ndarray   # camera + overlay
    .render_thermal(tframe, live_hotspot) -> np.ndarray     # cropped thermal view

FrameBus
    .publish_rgb(jpeg_bytes) / .publish_thermal(jpeg_bytes)
    .stream_rgb() -> generator[bytes] / .stream_thermal() -> generator[bytes]

HeatWebServer(bus, pipeline, host, port).start()    # Flask in daemon thread
```

Each unit is testable in isolation:
- `ThermalStream`: mock/fixture frame → assert rotation/crop dims + FOV.
- `VisionPipeline`: fixture image + synthetic `ThermalFrame` → returns regions and
  updates `RiskState`. No camera or board required.
- `DebugViewer`: canned `InferResult` → returns an `np.ndarray` of expected shape.
- `FrameBus`: publish then assert the stream generator yields the latest bytes.
- `HeatWebServer`: Flask test client → `/` returns 200 HTML; `/rgb.mjpg` returns
  the multipart content-type.

## Data flow

```
VisibleStream.read ─┐
                    ├─> main loop ──(every PREDICT_EVERY_N_FRAMES)──> VisionPipeline.submit
ThermalStream.read ─┘                                                      │
                                                                  [ViT background thread]
                                                                      │ risk.update
   DebugViewer.annotate_rgb / render_thermal <── try_take_result <──────┘
        │ (annotated np.ndarray x2)
        ▼  cv2.imencode -> JPEG
   FrameBus.publish_rgb / publish_thermal
        │
        ▼   (Flask daemon thread, per-client MJPEG generators)
   Browser:  GET /  ->  <img src=/rgb.mjpg>  +  <img src=/thermal.mjpg>
   Browser:  POST /control/density , /control/min_conf  ->  VisionPipeline live tuning
```

The background-inference threading model (latest-job-only queue, generation
counter, result lock) moves intact into `VisionPipeline`. The `RiskState` lock
stays internal to the pipeline; `DebugViewer` only reads `risk`. The web server is
a separate daemon thread reading the latest published frames — it never blocks the
capture/inference loop.

## Web interface details

- **Server:** Flask, `app.run(host=WEB_HOST, port=WEB_PORT, threaded=True)` in a
  daemon thread. Chosen for the simplest MJPEG multipart streaming; minimal dep.
- **Streaming:** `multipart/x-mixed-replace; boundary=frame`; each part is a JPEG.
- **Page:** one static HTML page, two `<img>` tags side-by-side (RGB left, thermal
  right) + small buttons posting to the control endpoints.
- **Live tuning parity:** the OpenCV `+/-` (grid density) and `,/.` (min
  confidence) keys become `POST /control/density?delta=±1` and
  `POST /control/min_conf?delta=±5`, applied to the running `VisionPipeline`. The
  `q`/Esc quit key is dropped (stop with Ctrl-C on the server).
- **Defaults:** `WEB_HOST=0.0.0.0` (reachable on the LAN), `WEB_PORT=8000`,
  overridable via env.

## Config & endpoint reconciliation

CapstoneDesign's `config.py` says `/stream/visible.mjpeg` + `/thermal/frame`; the
actual ESP32 firmware serves `/stream.mjpg` (thermal on `:81` for the unified
board). `config.py` will be set to match the firmware the board actually runs, with
`ESP32_HOST` and `HEAT_LOCAL=1` (webcam + mock thermal) env overrides preserved.
**Live URLs to be confirmed against the running board at implementation time.**

## Error handling (preserved from current behavior)

- RGB source stall: publish a "Waiting for stream…" error frame; reopen after N
  consecutive failures (network sources only).
- Thermal source unreachable: fall back to `MockThermalSource` with a log line.
- Hotspot projected outside RGB view: label out-of-view, skip classification.
- Browser disconnects: the MJPEG generator for that client ends; loop unaffected.

## Testing

- Extend existing `tests/` (already has `test_http_thermal_source.py`).
- `VisionPipeline` fixture-image test: regions returned + risk updated.
- `ThermalStream` rotation/crop dimension test.
- `DebugViewer` returns an `np.ndarray` of expected shape (no window).
- `FrameBus` publish/stream test.
- `HeatWebServer` Flask test-client: `/` is 200 HTML; `/rgb.mjpg` content-type is
  multipart; `POST /control/density` adjusts pipeline state.
- Manual `HEAT_LOCAL=1` smoke run: open `http://localhost:8000`, both feeds live,
  buttons retune, Ctrl-C stops cleanly.
- **Parity check:** decomposed pipeline behaves identically to the monolith on the
  same input before deleting `heat_algorithm.py`.

## Risks

- Background-inference threading is the delicate extraction; the parity check gates
  monolith deletion.
- MJPEG + a CPU-bound ViT model on one machine: ensure the web server thread reads
  *published* frames and never calls the model, so streaming stays smooth.
- Endpoint drift between `config.py` and firmware must be verified live.
- New `flask` dependency added to the laptop package.
