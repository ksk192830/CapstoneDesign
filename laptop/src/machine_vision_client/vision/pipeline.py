"""Vision pipeline: RGB + thermal -> material grid + hotspot material -> risk.

`VisionPipeline` owns the ViT model, a background `InferenceWorker` thread (so
the display/stream loop stays live while CPU inference runs ~1-2 s per batch),
and the running `RiskState`. Grid density and per-patch min-confidence are
live-tunable (`adjust_density` / `adjust_min_conf`), driven by the web controls.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForImageClassification

from machine_vision_client.materials import Material
from machine_vision_client.risk import RiskState
from machine_vision_client.thermal import (
    Hotspot,
    ThermalFrame,
    detect_hotspot,
    project_thermal_to_rgb,
    tile_peak_temp_c,
)

MODEL_NAME = "prithivMLmods/Minc-Materials-23"

PREDICT_EVERY_N_FRAMES = 15
CROP_SIZE = 224
HOTSPOT_THRESHOLD_C = 45.0

GRID_DENSITY_DEFAULT = 4
MIN_DENSITY = 1
MAX_DENSITY = 10
PATCH_MIN_CONFIDENCE = 20.0   # percent; suppress region below this
MIN_CONFIDENCE_FLOOR = 5.0
MAX_CONFIDENCE_CEILING = 80.0


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
                     tframe=None, proj_kwargs: dict | None = None):
    """Tile the frame into a cols x rows grid and classify every cell in one batch.

    If a `tframe` (ThermalFrame) is provided, each patch also gets a
    `peak_temp_c` - the hottest temperature in the thermal sub-region that
    corresponds to the RGB tile. `proj_kwargs` carries the effective thermal
    dims + FOV from the ThermalStream.
    """
    proj_kwargs = proj_kwargs or {}
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
        peak_t = (tile_peak_temp_c(tframe.temps_c, (x0, y0, x1, y1), w, h, **proj_kwargs)
                  if tframe is not None else float("nan"))
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


def grid_for_density(density: int, frame_w: int, frame_h: int) -> tuple[int, int]:
    cols = max(MIN_DENSITY, min(MAX_DENSITY, density))
    rows = max(1, round(cols * frame_h / frame_w))
    return cols, rows


@dataclass
class _InferJob:
    generation: int
    frame: np.ndarray
    temps_c: np.ndarray
    grid_cols: int
    grid_rows: int
    min_conf: float
    fw: int
    fh: int


@dataclass
class InferResult:
    generation: int
    patches: list
    regions: list
    hotspot: Optional[Hotspot]
    hotspot_rgb_xy: Optional[tuple[int, int]]
    label: str
    conf: float
    mat: Optional[Material]


class InferenceWorker:
    """Runs ViT grid + hotspot classification off the display thread.

    Only the latest pending job is kept so work does not queue up.
    """

    def __init__(self, processor, model, device, materials, risk, proj_kwargs):
        self._processor = processor
        self._model = model
        self._device = device
        self._materials = materials
        self._risk = risk
        self._proj = proj_kwargs
        self.risk_lock = threading.Lock()
        self._generation = 0
        self._job_q: queue.Queue[_InferJob] = queue.Queue(maxsize=1)
        self._result_lock = threading.Lock()
        self._latest: InferResult | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def bump_generation(self) -> int:
        with self._result_lock:
            self._generation += 1
            self._latest = None
        self._drain_jobs()
        return self._generation

    def submit(self, frame, tframe: ThermalFrame, grid_cols, grid_rows, min_conf) -> None:
        fh, fw = frame.shape[:2]
        job = _InferJob(
            generation=self._generation,
            frame=frame.copy(),
            temps_c=tframe.temps_c.copy(),
            grid_cols=grid_cols,
            grid_rows=grid_rows,
            min_conf=min_conf,
            fw=fw,
            fh=fh,
        )
        self._drain_jobs()
        try:
            self._job_q.put_nowait(job)
        except queue.Full:
            pass

    def try_take_result(self) -> InferResult | None:
        with self._result_lock:
            if self._latest is None or self._latest.generation != self._generation:
                return None
            out = self._latest
            self._latest = None
            return out

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)

    def _drain_jobs(self) -> None:
        try:
            while True:
                self._job_q.get_nowait()
        except queue.Empty:
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._job_q.get(timeout=0.05)
            except queue.Empty:
                continue
            if job.generation != self._generation:
                continue
            result = self._run(job)
            if result.generation != self._generation:
                continue
            with self._result_lock:
                self._latest = result

    def _run(self, job: _InferJob) -> InferResult:
        tframe = ThermalFrame(temps_c=job.temps_c, timestamp=time.time())
        patches = classify_patches(
            job.frame, self._processor, self._model, self._device,
            job.grid_cols, job.grid_rows, tframe=tframe, proj_kwargs=self._proj,
        )
        regions = aggregate_patches(patches, job.grid_cols, job.grid_rows, job.min_conf)
        hotspot = detect_hotspot(tframe, threshold_c=HOTSPOT_THRESHOLD_C)
        hotspot_rgb_xy: tuple[int, int] | None = None
        label, conf = "", 0.0
        mat: Optional[Material] = None

        if hotspot is not None:
            rx, ry, in_view = project_thermal_to_rgb(
                hotspot.x, hotspot.y, job.fw, job.fh, **self._proj
            )
            if in_view:
                hotspot_rgb_xy = (rx, ry)
                crop, _ = crop_around(job.frame, rx, ry, CROP_SIZE)
                label, conf = classify_top1(crop, self._processor, self._model, self._device)
                mat = self._materials.get(label)
            else:
                label, conf = "(hotspot out of RGB view)", 0.0
            with self.risk_lock:
                self._risk.update(hotspot.temp_c, mat)
        else:
            with self.risk_lock:
                self._risk.update(None, None)

        return InferResult(
            generation=job.generation,
            patches=patches,
            regions=regions,
            hotspot=hotspot,
            hotspot_rgb_xy=hotspot_rgb_xy,
            label=label,
            conf=conf,
            mat=mat,
        )


class VisionPipeline:
    """Owns the model, the background worker, risk, and live grid/conf tuning."""

    def __init__(self, materials, proj_kwargs: dict,
                 density: int = GRID_DENSITY_DEFAULT,
                 min_conf: float = PATCH_MIN_CONFIDENCE):
        self._materials = materials
        self._proj = proj_kwargs
        self.density = density
        self.min_conf = min_conf
        self.risk = RiskState()
        self._processor, self._model, self._device = load_model()
        self._worker = InferenceWorker(
            self._processor, self._model, self._device, materials, self.risk, proj_kwargs
        )
        self._last_dims: tuple[int, int] | None = None
        self.grid: tuple[int, int] = grid_for_density(density, 640, 480)

    @property
    def risk_lock(self) -> threading.Lock:
        return self._worker.risk_lock

    def _grid_for_frame(self, fw: int, fh: int) -> tuple[int, int]:
        if (fw, fh) != self._last_dims:
            self.grid = grid_for_density(self.density, fw, fh)
            self._last_dims = (fw, fh)
        return self.grid

    def submit(self, frame, tframe: ThermalFrame) -> None:
        fh, fw = frame.shape[:2]
        cols, rows = self._grid_for_frame(fw, fh)
        self._worker.submit(frame, tframe, cols, rows, self.min_conf)

    def try_take_result(self) -> InferResult | None:
        return self._worker.try_take_result()

    def adjust_density(self, delta: int) -> int:
        self.density = max(MIN_DENSITY, min(MAX_DENSITY, self.density + int(delta)))
        if self._last_dims is not None:
            self.grid = grid_for_density(self.density, *self._last_dims)
        self._worker.bump_generation()
        return self.density

    def adjust_min_conf(self, delta: float) -> float:
        self.min_conf = max(MIN_CONFIDENCE_FLOOR,
                            min(MAX_CONFIDENCE_CEILING, self.min_conf + float(delta)))
        self._worker.bump_generation()
        return self.min_conf

    def stop(self) -> None:
        self._worker.stop()
