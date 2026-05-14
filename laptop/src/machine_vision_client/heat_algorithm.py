"""Main loop: RGB + thermal -> material ID at hotspot -> risk score.

Pipeline (per the project flowchart):
  1. Read RGB frame from `RGB_SOURCE` — either a local webcam index
     (int) or an HTTP MJPEG URL exposed by an ESP32-P4 + OV5647 camera
     (see github.com/ksk192830/CapstoneDesign — protocol doc defines
     `GET /stream/visible.mjpeg`).
  2. Read thermal frame from `ThermalSource` (ESP32 + MLX90640 over USB
     serial; falls back to `MockThermalSource` if the port is missing).
  3. Detect a hotspot above `HOTSPOT_THRESHOLD_C`.
  4. Project the thermal hotspot into RGB coords (FOV-aware), crop a
     window around it, classify with Minc-Materials-23, look up the
     label in the Excel reference table.
  5. Update running risk score (TTI from temperature history when
     flammable material is identified).
  6. Render HUD.

Tuning knobs are module-level constants. Press 'q' in the OpenCV window
to quit.
"""

import os
import time
from typing import Optional

# `time` is also used inside HttpJpegSource below; keep the import here.

import cv2
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForImageClassification

from materials import Material, load_materials
from risk import RiskState
import numpy as np

from thermal import (
    Esp32ThermalSource,
    HttpThermalSource,
    MockThermalSource,
    ThermalFrame,
    THERMAL_W,
    THERMAL_H,
    THERMAL_FOV_H_DEG,
    THERMAL_FOV_V_DEG,
    detect_hotspot,
    project_thermal_to_rgb,
    render_thermal_view,
    tile_peak_temp_c,
)


# Counter-clockwise 90° rotations to apply to each incoming thermal frame.
# Use this when the MLX90640 is physically mounted rotated relative to the
# RGB camera. 0 = no rotation, 1 = CCW 90°, 2 = 180°, 3 = CW 90°.
THERMAL_ROTATE_CCW: int = 0  # 0/1/2/3 for 0/90/180/270 deg CCW rotation

# Effective thermal dims + FOV after rotation. An odd number of 90°
# rotations swaps width <-> height and H <-> V FOV.
if THERMAL_ROTATE_CCW % 2 == 1:
    EFF_THERMAL_W = THERMAL_H
    EFF_THERMAL_H = THERMAL_W
    EFF_THERMAL_FOV_H_DEG = THERMAL_FOV_V_DEG
    EFF_THERMAL_FOV_V_DEG = THERMAL_FOV_H_DEG
else:
    EFF_THERMAL_W = THERMAL_W
    EFF_THERMAL_H = THERMAL_H
    EFF_THERMAL_FOV_H_DEG = THERMAL_FOV_H_DEG
    EFF_THERMAL_FOV_V_DEG = THERMAL_FOV_V_DEG


def _proj_kwargs() -> dict:
    return dict(
        thermal_w=EFF_THERMAL_W, thermal_h=EFF_THERMAL_H,
        thermal_fov_h_deg=EFF_THERMAL_FOV_H_DEG,
        thermal_fov_v_deg=EFF_THERMAL_FOV_V_DEG,
    )


def rotate_thermal_frame(tframe: ThermalFrame) -> ThermalFrame:
    if THERMAL_ROTATE_CCW % 4 == 0:
        return tframe
    return ThermalFrame(
        temps_c=np.rot90(tframe.temps_c, k=THERMAL_ROTATE_CCW),
        timestamp=tframe.timestamp,
    )


MODEL_NAME = "prithivMLmods/Minc-Materials-23"

# RGB source: int = local webcam index, str = URL (HTTP MJPEG, RTSP, or
# a video file path). The reference firmware in ksk192830/CapstoneDesign
# (firmware/esp32-p4) exposes the OV5647 as `http://<esp32-ip>/stream.mjpg`
# (800x640 MJPEG). Note: docs/protocol.md says `/stream/visible.mjpeg`, but
# the actual http_camera_server.c registers `/stream.mjpg` — use the code.
# Examples:
#   RGB_SOURCE = 0
#   RGB_SOURCE = "http://<esp32-ip>/stream.mjpg"
RGB_SOURCE: int | str = 0  # 0 = local webcam; or "http://<esp32-ip>/capture/visible.jpg"
RGB_W = 640
RGB_H = 480
PREDICT_EVERY_N_FRAMES = 15
CROP_SIZE = 224
HOTSPOT_THRESHOLD_C = 45.0

# Thermal transport. Three options, picked in this order of preference:
#   THERMAL_HTTP_URL: str  -> HttpThermalSource against the unified
#       ESP32-P4 firmware (firmware/esp32-p4-unified). Use this when the
#       P4 is on Wi-Fi and exposing /thermal/frame.
#   THERMAL_PORT:     str  -> USB-serial source (legacy thermal-only
#       ESP32 running esp32_mlx90640.ino).
#   both None              -> MockThermalSource (Gaussian hot blob).
THERMAL_HTTP_URL: str | None = None  # e.g. "http://<esp32-ip>/thermal/frame"
THERMAL_PORT: str | None = None  # e.g. "/dev/cu.usbmodemXXXX" for USB-serial MLX90640
THERMAL_BAUD = 921600

# Patch-grid material scan: split the RGB frame into a grid of `density`
# columns; rows derived from the frame aspect ratio. Changeable live with
# +/- in the OpenCV window (capped at MIN/MAX_DENSITY).
GRID_DENSITY_DEFAULT = 4
MIN_DENSITY = 1
MAX_DENSITY = 10
PATCH_MIN_CONFIDENCE = 20.0   # percent; suppress region below this (',' / '.' adjusts live)
MIN_CONFIDENCE_FLOOR = 5.0
MAX_CONFIDENCE_CEILING = 80.0


class HttpJpegSource:
    """Polls a single-frame JPEG endpoint (e.g. /capture/visible.jpg).

    Mimics cv2.VideoCapture's `.read()` / `.isOpened()` / `.release()` so
    it slots in transparently. Why use this instead of an MJPEG stream:
    a long-lived MJPEG GET ties up the ESP32-P4's single HTTP server task
    forever, starving the thermal endpoint. Short JPEG GETs return the
    server to its select() loop between frames, so the thermal poller
    interleaves fine on the same port.
    """

    def __init__(self, url: str, timeout: float = 2.0, min_period_s: float = 0.2):
        """min_period_s caps the request rate (default 5 Hz). The ESP32-P4
        single-task HTTP server can only handle a few req/s before its
        socket pool saturates, so we throttle here rather than spam."""
        import urllib.request
        self.url = url
        self.timeout = timeout
        self.min_period_s = min_period_s
        self._urllib_request = urllib.request
        self._last_request_at = 0.0
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                self._first_data = resp.read()
            self._opened = True
            self._last_request_at = time.time()
        except Exception as e:
            print(f"[rgb-jpeg] initial probe failed: {e}")
            self._first_data = None
            self._opened = False

    def isOpened(self) -> bool:
        return self._opened

    def read(self):
        # Self-throttle: never less than min_period_s between requests.
        elapsed = time.time() - self._last_request_at
        if elapsed < self.min_period_s:
            time.sleep(self.min_period_s - elapsed)
        try:
            if self._first_data is not None:
                data = self._first_data
                self._first_data = None
            else:
                with self._urllib_request.urlopen(self.url, timeout=self.timeout) as resp:
                    data = resp.read()
        except Exception:
            self._last_request_at = time.time()
            return False, None
        self._last_request_at = time.time()
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return False, None
        return True, frame

    def release(self):
        pass

    def set(self, *args, **kwargs):
        pass


def open_rgb_capture(source: int | str):
    """Open `source` as a VideoCapture-shaped object.

    - int: local webcam via cv2.VideoCapture
    - URL ending in .jpg/.jpeg: HttpJpegSource (polled, plays nice with
      single-task HTTP servers)
    - any other URL (.mjpg, RTSP, file): cv2.VideoCapture
    """
    if isinstance(source, str) and source.lower().endswith((".jpg", ".jpeg")):
        cap = HttpJpegSource(source)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open RGB source: {source!r}")
        return cap

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open RGB source: {source!r}")
    if isinstance(source, int):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, RGB_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RGB_H)
    return cap


def make_error_frame(w: int, h: int, msg: str):
    import numpy as np
    frame = np.full((h, w, 3), 32, dtype="uint8")
    (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.putText(frame, msg, ((w - tw) // 2, (h + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return frame


def load_model():
    print("Loading model...")
    processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
    model = AutoModelForImageClassification.from_pretrained(MODEL_NAME)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if torch.backends.mps.is_available():
        device = "mps"
    model.to(device)
    print(f"Model loaded on: {device}")
    return processor, model, device


def crop_around(frame, cx: int, cy: int, size: int):
    h, w = frame.shape[:2]
    x0 = max(0, cx - size // 2)
    y0 = max(0, cy - size // 2)
    x1 = min(w, x0 + size)
    y1 = min(h, y0 + size)
    x0 = max(0, x1 - size)
    y0 = max(0, y1 - size)
    return frame[y0:y1, x0:x1], (x0, y0, x1, y1)


def classify_top1(bgr, processor, model, device) -> tuple[str, float]:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    inputs = processor(images=img, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        out = model(**inputs)
        probs = torch.softmax(out.logits, dim=1)[0]
    top_p, top_id = torch.max(probs, dim=0)
    label = model.config.id2label[int(top_id.item())]
    return label, float(top_p.item() * 100)


def classify_patches(frame, processor, model, device, cols: int, rows: int,
                     tframe=None):
    """Tile the frame into a cols x rows grid and classify every cell in one batch.

    If a `tframe` (ThermalFrame) is provided, each patch also gets a
    `peak_temp_c` — the hottest temperature in the thermal sub-region
    that corresponds to the RGB tile.

    Returns list of dicts (row-major): each has cell bbox + center + top-1.
    """
    h, w = frame.shape[:2]
    pw, ph = w // cols, h // rows
    images = []
    boxes = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * pw, r * ph
            x1 = w if c == cols - 1 else x0 + pw
            y1 = h if r == rows - 1 else y0 + ph
            patch = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)
            images.append(Image.fromarray(patch))
            boxes.append((x0, y0, x1, y1))

    inputs = processor(images=images, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        out = model(**inputs)
        probs = torch.softmax(out.logits, dim=1)
    top_p, top_id = torch.max(probs, dim=1)

    out_list = []
    for (x0, y0, x1, y1), p, idx in zip(boxes, top_p.tolist(), top_id.tolist()):
        peak_t = (tile_peak_temp_c(
                    tframe.temps_c, (x0, y0, x1, y1), w, h,
                    thermal_w=EFF_THERMAL_W, thermal_h=EFF_THERMAL_H,
                    thermal_fov_h_deg=EFF_THERMAL_FOV_H_DEG,
                    thermal_fov_v_deg=EFF_THERMAL_FOV_V_DEG,
                  ) if tframe is not None else float("nan"))
        out_list.append({
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "cx": (x0 + x1) // 2,
            "cy": (y0 + y1) // 2,
            "label": model.config.id2label[int(idx)],
            "conf": float(p * 100),
            "peak_temp_c": peak_t,
        })
    return out_list


def aggregate_patches(patches, cols: int, rows: int, min_conf: float):
    """Group 4-connected same-label patches into regions (BFS flood-fill)."""
    grid = [[patches[r * cols + c] for c in range(cols)] for r in range(rows)]
    visited = [[False] * cols for _ in range(rows)]
    regions = []
    for r in range(rows):
        for c in range(cols):
            if visited[r][c]:
                continue
            p = grid[r][c]
            if p["conf"] < min_conf:
                visited[r][c] = True
                continue
            label = p["label"]
            stack = [(r, c)]
            cells = []
            while stack:
                rr, cc = stack.pop()
                if rr < 0 or rr >= rows or cc < 0 or cc >= cols or visited[rr][cc]:
                    continue
                pp = grid[rr][cc]
                if pp["conf"] < min_conf or pp["label"] != label:
                    continue
                visited[rr][cc] = True
                cells.append(pp)
                stack.extend([(rr + 1, cc), (rr - 1, cc), (rr, cc + 1), (rr, cc - 1)])
            if not cells:
                continue
            x0 = min(cc["x0"] for cc in cells)
            y0 = min(cc["y0"] for cc in cells)
            x1 = max(cc["x1"] for cc in cells)
            y1 = max(cc["y1"] for cc in cells)
            peak_temps = [cc.get("peak_temp_c") for cc in cells
                          if cc.get("peak_temp_c") is not None
                          and cc.get("peak_temp_c") == cc.get("peak_temp_c")]
            peak_temp_c = max(peak_temps) if peak_temps else float("nan")
            regions.append({
                "label": label,
                "avg_conf": sum(cc["conf"] for cc in cells) / len(cells),
                "n_cells": len(cells),
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "cell_boxes": [(cc["x0"], cc["y0"], cc["x1"], cc["y1"]) for cc in cells],
                "peak_temp_c": peak_temp_c,
            })
    return regions


WARM_THRESHOLD_C = 35.0   # below this, tile is treated as ambient (gray)


def _is_nan(x) -> bool:
    return x is None or x != x


def _region_color(material, peak_temp_c) -> tuple[int, int, int]:
    """BGR fill color for a region tile, tiered by its own peak temperature.

    - Non-material (sky etc.): gray.
    - Temp unknown / below WARM_THRESHOLD_C: gray (no significant heat).
    - Flammable with AIT data: tier by `peak_temp / AIT_lo`.
        <50% green, <75% yellow, <100% orange, >=100% red.
    - Anything else with heat: tier by raw temperature bands.
        <50C green, <100C yellow, <200C orange, >=200C red.
    """
    if material is None or not material.is_material:
        return (130, 130, 130)
    if _is_nan(peak_temp_c) or peak_temp_c < WARM_THRESHOLD_C:
        return (130, 130, 130)
    if material.flammable and material.ignition_c is not None:
        ait_lo = material.ignition_c[0]
        frac = (peak_temp_c / ait_lo) if ait_lo > 0 else 0.0
        if frac < 0.5:  return (60, 200, 60)
        if frac < 0.75: return (40, 220, 220)
        if frac < 1.0:  return (40, 140, 240)
        return (40, 40, 240)
    t = peak_temp_c
    if t < 50:  return (60, 200, 60)
    if t < 100: return (40, 220, 220)
    if t < 200: return (40, 140, 240)
    return (40, 40, 240)


def _font_scale_for_cell(cell_w: int, cell_h: int) -> float:
    s = min(cell_w, cell_h)
    if s >= 180:
        return 0.55
    if s >= 130:
        return 0.45
    if s >= 90:
        return 0.38
    return 0.32


def draw_regions(frame, regions, materials, alpha: float = 0.22):
    """Translucent fill per cell + one inset top-left label per region.

    Tile colors come from `_region_color(material, region.peak_temp_c)`,
    so every region is independently tiered by its own peak temperature.
    """
    if not regions:
        return

    overlay = frame.copy()
    for r in regions:
        color = _region_color(materials.get(r["label"]), r.get("peak_temp_c"))
        for x0, y0, x1, y1 in r["cell_boxes"]:
            cv2.rectangle(overlay, (x0, y0), (x1, y1), color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)

    for r in regions:
        color = _region_color(materials.get(r["label"]), r.get("peak_temp_c"))
        cx0, cy0, cx1, cy1 = r["cell_boxes"][0]
        scale = _font_scale_for_cell(cx1 - cx0, cy1 - cy0)
        text = f"{r['label']} {r['avg_conf']:.0f}%"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        tx = r["x0"] + 4
        ty = r["y0"] + th + 4
        cv2.rectangle(frame, (tx - 2, ty - th - 2), (tx + tw + 2, ty + 2), (0, 0, 0), -1)
        cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1)


def grid_for_density(density: int, frame_w: int, frame_h: int) -> tuple[int, int]:
    cols = max(MIN_DENSITY, min(MAX_DENSITY, density))
    rows = max(1, round(cols * frame_h / frame_w))
    return cols, rows


def risk_color_bgr(score: int) -> tuple[int, int, int]:
    """Tiered color for the risk score: gray / green / yellow / orange / red."""
    if score <= 0:
        return (180, 180, 180)
    if score < 5:
        return (60, 200, 60)
    if score < 15:
        return (40, 220, 220)
    if score < 30:
        return (40, 140, 240)
    return (40, 40, 240)


def draw_hud(frame, risk, hotspot, hotspot_rgb_xy, mat, fps):
    """Top-left panel + on-image hotspot crosshair.

    Layout (5 lines, top-left, semi-transparent black backdrop):
      RISK <n>            (big, color-tiered by tier)
      <event>             (current risk event, single line)
      hotspot <T>C -> <material> (AIT <lo>-<hi>C)
      <fps> fps           (small)
    Hotspot marker is drawn at the projected RGB coordinate.
    """
    h, w = frame.shape[:2]

    # Hotspot crosshair + temp label on the RGB image.
    if hotspot is not None and hotspot_rgb_xy is not None:
        rx, ry = hotspot_rgb_xy
        cv2.drawMarker(frame, (rx, ry), (255, 255, 255),
                       cv2.MARKER_CROSS, 30, 2)
        cv2.drawMarker(frame, (rx, ry), (0, 0, 0),
                       cv2.MARKER_CROSS, 28, 1)
        tag = f"{hotspot.temp_c:.0f}C"
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        tx = max(0, min(w - tw - 6, rx + 18))
        ty = max(th + 6, ry - 10)
        cv2.rectangle(frame, (tx - 4, ty - th - 4),
                      (tx + tw + 4, ty + 4), (0, 0, 0), -1)
        cv2.putText(frame, tag, (tx, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    # Semi-transparent HUD backdrop (top-left).
    panel_w = min(380, w)
    panel_h = 110
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, dst=frame)

    # Big risk score.
    score = int(risk.score)
    cv2.putText(frame, f"RISK {score}", (10, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, risk_color_bgr(score), 3,
                cv2.LINE_AA)

    # Event line.
    event = (risk.last_event or "idle")[:46]
    cv2.putText(frame, event, (10, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 255, 255) if score > 0 else (200, 200, 200),
                1, cv2.LINE_AA)

    # Hotspot + material + AIT line.
    if hotspot is not None:
        line = f"hotspot {hotspot.temp_c:.0f}C"
        if mat is not None and mat.is_material:
            line += f"  ->  {mat.label}"
            if mat.ignition_c is not None:
                line += f" (AIT {mat.ignition_c[0]:.0f}-{mat.ignition_c[1]:.0f}C)"
            elif not mat.flammable:
                line += " (non-flam)"
        elif mat is not None:
            line += f"  ->  {mat.label} (n/a)"
    else:
        line = "no heat source"
    cv2.putText(frame, line[:50], (10, 92),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220),
                1, cv2.LINE_AA)

    # FPS.
    cv2.putText(frame, f"{fps:.1f} fps", (10, panel_h - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 160),
                1, cv2.LINE_AA)


def format_status(fps, hotspot, label, conf, mat, risk, grid_cols, grid_rows) -> str:
    hs = (f"hotspot={hotspot.temp_c:.1f}C@({hotspot.x},{hotspot.y})"
          if hotspot is not None else "hotspot=none")
    if mat is not None and mat.ignition_c is not None:
        ait = f"  AIT={mat.ignition_c[0]:.0f}-{mat.ignition_c[1]:.0f}C"
    else:
        ait = ""
    matstr = f"  material={label} {conf:.0f}%" if label else ""
    return (f"fps={fps:4.1f}  grid={grid_cols}x{grid_rows}  {hs}{matstr}{ait}"
            f"  risk={risk.score}  [{risk.last_event}]")


RGB_WIN = f"Fire Risk - RGB [pid {os.getpid()}]"
THERMAL_WIN = f"Fire Risk - Thermal [pid {os.getpid()}]"


def main():
    materials = load_materials()
    print(f"Loaded {len(materials)} materials from xlsx.")
    print(f"OpenCV windows: '{RGB_WIN}' and '{THERMAL_WIN}'")

    processor, model, device = load_model()

    print(f"Opening RGB source: {RGB_SOURCE!r}")
    cap = open_rgb_capture(RGB_SOURCE)

    if THERMAL_HTTP_URL:
        try:
            thermal = HttpThermalSource(THERMAL_HTTP_URL)
        except Exception as e:
            print(f"[thermal] could not reach {THERMAL_HTTP_URL} ({e}); falling back to mock")
            thermal = MockThermalSource()
    elif THERMAL_PORT:
        try:
            thermal = Esp32ThermalSource(THERMAL_PORT, THERMAL_BAUD)
        except Exception as e:
            print(f"[thermal] could not open {THERMAL_PORT} ({e}); falling back to mock")
            thermal = MockThermalSource()
    else:
        thermal = MockThermalSource()
    risk = RiskState()

    frame_count = 0
    label, conf = "", 0.0
    mat: Optional[Material] = None
    hotspot = None
    hotspot_rgb_xy: tuple[int, int] | None = None
    patches: list[dict] = []
    regions: list[dict] = []

    density = GRID_DENSITY_DEFAULT
    grid_cols, grid_rows = grid_for_density(density, RGB_W, RGB_H)
    last_grid_dims = (RGB_W, RGB_H)
    min_conf = PATCH_MIN_CONFIDENCE

    prev_time = time.time()
    fps = 0.0

    print("Press 'q' to quit. '+' / '-' adjusts grid density. ',' / '.' adjusts min confidence.")
    consecutive_failures = 0
    is_network_source = isinstance(RGB_SOURCE, str)
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            consecutive_failures += 1
            if is_network_source and consecutive_failures < 30:
                cv2.imshow("Heat Algorithm",
                           make_error_frame(RGB_W, RGB_H, "Waiting for stream..."))
                if cv2.waitKey(33) & 0xFF == ord("q"):
                    break
                if consecutive_failures % 10 == 0:
                    print(f"[rgb] stream stalled; reopening {RGB_SOURCE!r}")
                    cap.release()
                    try:
                        cap = open_rgb_capture(RGB_SOURCE)
                    except RuntimeError as e:
                        print(f"[rgb] reopen failed: {e}")
                continue
            print("Failed to receive frame.")
            break
        consecutive_failures = 0
        frame_count += 1

        now = time.time()
        dt = now - prev_time
        if dt > 0:
            fps = 1.0 / dt
        prev_time = now

        tframe = rotate_thermal_frame(thermal.read())

        fh, fw = frame.shape[:2]
        # Keep the grid aspect ratio synced with the actual incoming frame
        # — firmware emits 800x640, not the RGB_W/RGB_H defaults.
        if (fw, fh) != last_grid_dims:
            grid_cols, grid_rows = grid_for_density(density, fw, fh)
            last_grid_dims = (fw, fh)

        if frame_count % PREDICT_EVERY_N_FRAMES == 0:
            patches = classify_patches(
                frame, processor, model, device, grid_cols, grid_rows,
                tframe=tframe,
            )
            regions = aggregate_patches(
                patches, grid_cols, grid_rows, min_conf
            )

            hotspot = detect_hotspot(tframe, threshold_c=HOTSPOT_THRESHOLD_C)

            if hotspot is not None:
                rx, ry, in_view = project_thermal_to_rgb(
                    hotspot.x, hotspot.y, fw, fh, **_proj_kwargs()
                )
                if in_view:
                    hotspot_rgb_xy = (rx, ry)
                    crop, _ = crop_around(frame, rx, ry, CROP_SIZE)
                    label, conf = classify_top1(crop, processor, model, device)
                    mat = materials.get(label)
                else:
                    hotspot_rgb_xy = None
                    label, conf = "(hotspot out of RGB view)", 0.0
                    mat = None
                risk.update(hotspot.temp_c, mat)
            else:
                hotspot_rgb_xy = None
                label, conf = "", 0.0
                mat = None
                risk.update(None, None)

            print(format_status(fps, hotspot, label, conf, mat, risk,
                                grid_cols, grid_rows))

        draw_regions(frame, regions, materials)
        draw_hud(frame, risk, hotspot, hotspot_rgb_xy, mat, fps)
        cv2.imshow(RGB_WIN, frame)
        cv2.imshow(THERMAL_WIN, render_thermal_view(tframe, hotspot))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key in (ord("+"), ord("=")):
            density = min(MAX_DENSITY, density + 1)
            grid_cols, grid_rows = grid_for_density(density, *last_grid_dims)
            patches, regions = [], []
        elif key in (ord("-"), ord("_")):
            density = max(MIN_DENSITY, density - 1)
            grid_cols, grid_rows = grid_for_density(density, *last_grid_dims)
            patches, regions = [], []
        elif key == ord("."):
            min_conf = min(MAX_CONFIDENCE_CEILING, min_conf + 5.0)
            regions = aggregate_patches(patches, grid_cols, grid_rows, min_conf)
            print(f"min_conf -> {min_conf:.0f}%")
        elif key == ord(","):
            min_conf = max(MIN_CONFIDENCE_FLOOR, min_conf - 5.0)
            regions = aggregate_patches(patches, grid_cols, grid_rows, min_conf)
            print(f"min_conf -> {min_conf:.0f}%")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
