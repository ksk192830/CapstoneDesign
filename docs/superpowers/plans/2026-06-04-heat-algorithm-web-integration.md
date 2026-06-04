# Heat Algorithm Web Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Decompose `heat_algorithm.py` into CapstoneDesign's `machine_vision_client` module slots and serve two live feeds (RGB+overlay, cropped thermal) from a laptop Flask web server.

**Architecture:** `video/` provides RGB + thermal sources; `vision/VisionPipeline` runs the ViT model on a background thread and owns risk; `ui/DebugViewer` annotates frames (no windows); `ui/web_server.py` streams them as MJPEG; `main.py` orchestrates the loop and publishes frames to a `FrameBus`. No car control.

**Tech Stack:** Python, OpenCV, PyTorch/transformers, Flask (new), numpy.

**Spec:** `docs/superpowers/specs/2026-06-04-heat-algorithm-integration-design.md`

---

### Task 1: config.py — drop car keys, reconcile endpoints, add web settings
**Files:** Modify `laptop/src/machine_vision_client/config.py`
- Remove `FIRMWARE_PROFILE`, `CAR_CONTROL_ENABLED`, `MOTOR_BASE_URL`, `CONTROL_WS_URL`, profile branch.
- Set unified-board endpoints: `VISIBLE_STREAM_URL=http://{host}/stream.mjpg`, `THERMAL_FRAME_URL=http://{host}:81/thermal/frame`.
- Add `WEB_HOST` (default `0.0.0.0`), `WEB_PORT` (default `8000`).
- Keep `RGB_SOURCE`, `THERMAL_HTTP_URL`, `THERMAL_PORT`, `THERMAL_BAUD`, `RGB_W/H`, `LOCAL_DEV`.
- [ ] Verify: `python -c "import machine_vision_client.config as c; print(c.WEB_PORT, c.RGB_SOURCE)"`
- [ ] Commit.

### Task 2: video/thermal_stream.py — ThermalStream (source + alignment)
**Files:** Modify `video/thermal_stream.py`; Test `tests/test_thermal_stream.py`
- Move alignment knobs (`THERMAL_ROTATE_CCW/MIRROR_H/CROP_*`), `align_frame` (was `rotate_thermal_frame`), `EFF_THERMAL_*` derivation, source selection (HTTP→serial→mock).
- `ThermalStream.read() -> ThermalFrame` (aligned); `.proj_kwargs()`; class attrs `eff_w/eff_h/eff_fov_h_deg/eff_fov_v_deg`.
- [ ] Test: feed a 24×32 frame to `align_frame`, assert shape `(16, 14)` and `(ThermalStream.eff_h, ThermalStream.eff_w) == (16, 14)`.
- [ ] Run test, commit.

### Task 3: video/visible_stream.py — absorb RGB source helpers
**Files:** Modify `video/visible_stream.py`
- Add `HttpJpegSource`, `open_rgb_capture`, `make_error_frame` (verbatim from monolith).
- `VisibleStream(source=RGB_SOURCE)` with `.open()/.read()->frame|None/.reopen()/.release()`.
- [ ] Verify import. Commit.

### Task 4: vision/pipeline.py — VisionPipeline (model + worker + risk)
**Files:** Modify `vision/pipeline.py`; Test `tests/test_pipeline_helpers.py`
- Module fns: `load_model`, `crop_around`, `classify_top1`, `classify_patches(...,proj_kwargs)`, `aggregate_patches`, `grid_for_density`. Constants: `MODEL_NAME`, `PREDICT_EVERY_N_FRAMES`, `CROP_SIZE`, `HOTSPOT_THRESHOLD_C`, density/confidence bounds.
- `InferenceWorker` (takes `proj_kwargs`), public `InferResult` dataclass, internal `_InferJob`.
- `VisionPipeline(materials, proj_kwargs)`: owns `risk`, `density`, `min_conf`, `.submit(frame,tframe)`, `.try_take_result()`, `.adjust_density(d)`, `.adjust_min_conf(d)`, `.grid`, `.risk_lock`, `.stop()`.
- [ ] Test pure helpers (no model download): `grid_for_density`, `aggregate_patches`, `crop_around`.
- [ ] Run test, commit.

### Task 5: ui/debug_viewer.py — DebugViewer (drawing only)
**Files:** Modify `ui/debug_viewer.py`; Test `tests/test_debug_viewer.py`
- Move `draw_regions`, `_region_color`, `WARM_THRESHOLD_C`, `risk_color_bgr`, `draw_hud`, `format_status`, `_font_scale_for_cell`.
- `DebugViewer(materials).annotate_rgb(frame, result, risk, fps)->ndarray`, `.render_thermal(tframe, live_hotspot)->ndarray`.
- [ ] Test: `annotate_rgb` on a black frame + `result=None` returns same-shape ndarray.
- [ ] Run test, commit.

### Task 6: ui/web_server.py — FrameBus + HeatWebServer (new)
**Files:** Create `ui/web_server.py`; Test `tests/test_web_server.py`
- `FrameBus`: `publish(which,jpg)`, `stream(which)` generator (condition-based, keepalive).
- `HeatWebServer(bus,pipeline,host,port)`: routes `/`, `/rgb.mjpg`, `/thermal.mjpg`, `POST /control/density`, `POST /control/min_conf`; `.start()` daemon thread.
- [ ] Test (Flask test client + stub pipeline): `/` 200 & contains `rgb.mjpg`; `POST /control/density?delta=1` updates stub.
- [ ] Run test, commit.

### Task 7: main.py — orchestrator
**Files:** Modify `main.py`
- Wire VisibleStream + ThermalStream + VisionPipeline + DebugViewer + FrameBus + HeatWebServer; loop reads, submits every N, annotates, JPEG-encodes, publishes; RGB stall→error frame+reopen; frame pacing sleep; Ctrl-C/finally stops pipeline.
- [ ] Verify import. Commit.

### Task 8: pyproject + heat_algorithm shim + cleanup
**Files:** Modify `laptop/pyproject.toml`, `heat_algorithm.py`
- Add `flask` dep; install into `.venv`.
- Reduce `heat_algorithm.py` to a shim re-exporting `main` from package modules (back-compat for root `heat_algorithm` launcher), or delete after parity check.
- [ ] `pip install -e laptop/`; run full test suite.
- [ ] Manual `HEAT_LOCAL=1` smoke (open `http://localhost:8000`). Commit.

## Self-review
- Spec coverage: every module-map row → a task. ✓
- Types consistent: `InferResult`, `proj_kwargs`, `adjust_density/min_conf`, `FrameBus.publish/stream` used identically across tasks. ✓
