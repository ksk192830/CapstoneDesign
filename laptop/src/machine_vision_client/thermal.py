"""Thermal-camera abstraction and hotspot detection.

For development we use `MockThermalSource`, which simulates an MLX90640
(32x24) frame with a Gaussian hot blob that rises in temperature over
time. `Esp32ThermalSource` is a stub for the real device — fill in the
transport once the firmware exposes a temperature endpoint.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

import numpy as np

try:
    import serial  # pyserial
except ImportError:
    serial = None

try:
    import cv2
except ImportError:
    cv2 = None


# MLX90640 wide-angle variant: 32x24 sensor, ~110° H x 75° V FOV.
THERMAL_W = 32
THERMAL_H = 24
THERMAL_FOV_H_DEG = 110.0
THERMAL_FOV_V_DEG = 75.0

# Pi Camera Rev 1.3 / OV5647 with the stock 3.6 mm lens cropped to the
# firmware's 800x640 capture window — ~53° H x 41° V. Override at the
# call site if you measure your actual camera's FOV with a calibration
# target. (For the built-in MacBook webcam, use 70 H x 53 V.)
RGB_FOV_H_DEG_DEFAULT = 53.0
RGB_FOV_V_DEG_DEFAULT = 41.0


@dataclass
class ThermalFrame:
    temps_c: np.ndarray
    timestamp: float


@dataclass
class Hotspot:
    x: int
    y: int
    temp_c: float
    area_px: int


class ThermalSource(Protocol):
    def read(self) -> ThermalFrame: ...


class MockThermalSource:
    """Ambient background + a Gaussian hot blob that warms toward `target_c`."""

    def __init__(
        self,
        ambient_c: float = 24.0,
        hotspot_xy: tuple[int, int] = (THERMAL_W // 2, THERMAL_H // 2),
        target_c: float = 400.0,
        rise_rate_c_per_s: float = 6.0,
        sigma: float = 3.0,
        noise_std: float = 0.4,
        seed: int = 0,
    ):
        self.ambient_c = ambient_c
        self.hotspot_xy = hotspot_xy
        self.target_c = target_c
        self.rise_rate_c_per_s = rise_rate_c_per_s
        self.sigma = sigma
        self.noise_std = noise_std
        self._t0 = time.time()
        self._rng = np.random.default_rng(seed)

    def _current_peak_c(self) -> float:
        elapsed = time.time() - self._t0
        rise = min(self.target_c - self.ambient_c, self.rise_rate_c_per_s * elapsed)
        return float(self.ambient_c + max(0.0, rise))

    def read(self) -> ThermalFrame:
        peak = self._current_peak_c()
        ys, xs = np.indices((THERMAL_H, THERMAL_W))
        hx, hy = self.hotspot_xy
        gauss = np.exp(-((xs - hx) ** 2 + (ys - hy) ** 2) / (2 * self.sigma**2))
        temps = self.ambient_c + (peak - self.ambient_c) * gauss
        temps = temps + self._rng.normal(0.0, self.noise_std, temps.shape)
        return ThermalFrame(temps_c=temps.astype(np.float32), timestamp=time.time())


class Esp32ThermalSource:
    """USB-serial client for the ESP32 + MLX90640 firmware.

    Matches the wire format produced by `esp32_mlx90640/esp32_mlx90640.ino`:
        {"ts":<millis>,"temps_c":[t0,t1,...,t767]}
    one frame per newline, 921600 baud. A background thread keeps reading
    and stores the most recent frame so `read()` never blocks.
    """

    def __init__(
        self,
        port: str,
        baud: int = 921600,
        rows: int = THERMAL_H,
        cols: int = THERMAL_W,
    ):
        if serial is None:
            raise RuntimeError("pyserial is not installed (uv pip install pyserial)")
        self.port = port
        self.baud = baud
        self.rows = rows
        self.cols = cols
        self._ser = serial.Serial(port, baud, timeout=1.0)
        self._latest: ThermalFrame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print(f"[thermal] streaming from {port} @ {baud} baud")

    def _read_loop(self) -> None:
        n_expected = self.rows * self.cols
        while not self._stop.is_set():
            try:
                line = self._ser.readline()
            except Exception as e:
                print(f"[thermal] read error: {e}")
                time.sleep(0.5)
                continue
            if not line or not line.startswith(b"{"):
                continue
            try:
                data = json.loads(line.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                continue
            if "event" in data:
                print(f"[thermal] esp32 event: {data}")
                continue
            temps = data.get("temps_c")
            if not isinstance(temps, list) or len(temps) != n_expected:
                continue
            arr = np.array(temps, dtype=np.float32).reshape(self.rows, self.cols)
            with self._lock:
                self._latest = ThermalFrame(temps_c=arr, timestamp=time.time())

    def read(self) -> ThermalFrame:
        with self._lock:
            if self._latest is not None:
                return self._latest
        return ThermalFrame(
            temps_c=np.full((self.rows, self.cols), 24.0, dtype=np.float32),
            timestamp=time.time(),
        )

    def close(self) -> None:
        self._stop.set()
        try:
            self._ser.close()
        except Exception:
            pass


class HttpThermalSource:
    """Polls `GET /thermal/frame` on the ESP32-P4 unified firmware.

    Wire format (matches `esp32_mlx90640.ino` and the unified firmware's
    `thermal_frame_handler`):
        {"ts": <ms>, "temps_c": [t0, ..., t767]}
        or
        {"event": "warming_up"}   -> source returns ambient until real data arrives.

    A background thread keeps the latest frame fresh; `read()` never
    blocks on HTTP. Transient errors are logged at most once per minute
    and the last good frame is held; `read()` never raises.
    """

    def __init__(self, url: str, poll_hz: float = 4.0, timeout: float = 1.0,
                 rows: int = THERMAL_H, cols: int = THERMAL_W):
        self.url = url
        self.timeout = float(timeout)
        self.rows = rows
        self.cols = cols
        self._period = 1.0 / max(0.5, float(poll_hz))
        self._latest: ThermalFrame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_err_ts = 0.0
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[thermal] polling {url} @ ~{poll_hz:.0f} Hz")

    def _poll_loop(self) -> None:
        n_expected = self.rows * self.cols
        while not self._stop.is_set():
            t0 = time.time()
            try:
                with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                    body = resp.read()
                data = json.loads(body.decode("utf-8", errors="ignore"))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                now = time.time()
                if now - self._last_err_ts > 60.0:
                    print(f"[thermal] http poll error: {e}")
                    self._last_err_ts = now
                self._sleep_to_period(t0)
                continue

            if isinstance(data, dict) and "event" in data:
                self._sleep_to_period(t0)
                continue

            temps = data.get("temps_c") if isinstance(data, dict) else None
            if not isinstance(temps, list) or len(temps) != n_expected:
                self._sleep_to_period(t0)
                continue

            arr = np.asarray(temps, dtype=np.float32).reshape(self.rows, self.cols)
            with self._lock:
                self._latest = ThermalFrame(temps_c=arr, timestamp=time.time())
            self._sleep_to_period(t0)

    def _sleep_to_period(self, started_at: float) -> None:
        elapsed = time.time() - started_at
        delay = self._period - elapsed
        if delay > 0:
            self._stop.wait(delay)

    def read(self) -> ThermalFrame:
        with self._lock:
            if self._latest is not None:
                return self._latest
        return ThermalFrame(
            temps_c=np.full((self.rows, self.cols), 24.0, dtype=np.float32),
            timestamp=time.time(),
        )

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)


def project_rgb_to_thermal(
    rx: float,
    ry: float,
    rgb_w: int,
    rgb_h: int,
    rgb_fov_h_deg: float = RGB_FOV_H_DEG_DEFAULT,
    rgb_fov_v_deg: float = RGB_FOV_V_DEG_DEFAULT,
    thermal_w: int = THERMAL_W,
    thermal_h: int = THERMAL_H,
    thermal_fov_h_deg: float = THERMAL_FOV_H_DEG,
    thermal_fov_v_deg: float = THERMAL_FOV_V_DEG,
) -> tuple[int, int]:
    """Map an RGB pixel to the corresponding thermal pixel via FOV math.

    Inverse of `project_thermal_to_rgb`. Result is clamped to the
    thermal grid, so a corner near the edge maps to the nearest valid
    thermal pixel rather than overflowing. The thermal_* kwargs let
    callers override the defaults (used when the thermal frame has been
    rotated and so has different effective dims / FOV than the sensor's
    native orientation).
    """
    ax = (rx / rgb_w - 0.5) * rgb_fov_h_deg
    ay = (ry / rgb_h - 0.5) * rgb_fov_v_deg
    tx = (ax / thermal_fov_h_deg + 0.5) * thermal_w
    ty = (ay / thermal_fov_v_deg + 0.5) * thermal_h
    return (
        max(0, min(thermal_w - 1, int(round(tx)))),
        max(0, min(thermal_h - 1, int(round(ty)))),
    )


def tile_peak_temp_c(
    temps_c: np.ndarray,
    rgb_box: tuple[int, int, int, int],
    rgb_w: int,
    rgb_h: int,
    rgb_fov_h_deg: float = RGB_FOV_H_DEG_DEFAULT,
    rgb_fov_v_deg: float = RGB_FOV_V_DEG_DEFAULT,
    thermal_w: int = THERMAL_W,
    thermal_h: int = THERMAL_H,
    thermal_fov_h_deg: float = THERMAL_FOV_H_DEG,
    thermal_fov_v_deg: float = THERMAL_FOV_V_DEG,
) -> float:
    """Peak temperature within the thermal subarray that corresponds to
    the given RGB bounding box. Returns NaN if the projection is empty.
    """
    x0, y0, x1, y1 = rgb_box
    kwargs = dict(rgb_fov_h_deg=rgb_fov_h_deg, rgb_fov_v_deg=rgb_fov_v_deg,
                  thermal_w=thermal_w, thermal_h=thermal_h,
                  thermal_fov_h_deg=thermal_fov_h_deg,
                  thermal_fov_v_deg=thermal_fov_v_deg)
    tx0, ty0 = project_rgb_to_thermal(x0, y0, rgb_w, rgb_h, **kwargs)
    tx1, ty1 = project_rgb_to_thermal(x1, y1, rgb_w, rgb_h, **kwargs)
    a, b = min(tx0, tx1), max(tx0, tx1) + 1
    c, d = min(ty0, ty1), max(ty0, ty1) + 1
    sub = temps_c[c:d, a:b]
    if sub.size == 0:
        return float("nan")
    return float(sub.max())


def project_thermal_to_rgb(
    tx: float,
    ty: float,
    rgb_w: int,
    rgb_h: int,
    rgb_fov_h_deg: float = RGB_FOV_H_DEG_DEFAULT,
    rgb_fov_v_deg: float = RGB_FOV_V_DEG_DEFAULT,
    thermal_w: int = THERMAL_W,
    thermal_h: int = THERMAL_H,
    thermal_fov_h_deg: float = THERMAL_FOV_H_DEG,
    thermal_fov_v_deg: float = THERMAL_FOV_V_DEG,
) -> tuple[int, int, bool]:
    """Map a thermal pixel to an RGB pixel via angular co-axial projection.

    Returns (rx, ry, in_view). `in_view` is False when the thermal pixel
    points outside the RGB camera's narrower FOV (so the hotspot is
    physically not visible to the RGB stream).
    """
    ax = (tx / thermal_w - 0.5) * thermal_fov_h_deg
    ay = (ty / thermal_h - 0.5) * thermal_fov_v_deg
    half_rgb_h = rgb_fov_h_deg / 2
    half_rgb_v = rgb_fov_v_deg / 2
    in_view = -half_rgb_h <= ax <= half_rgb_h and -half_rgb_v <= ay <= half_rgb_v
    rx = (ax / rgb_fov_h_deg + 0.5) * rgb_w
    ry = (ay / rgb_fov_v_deg + 0.5) * rgb_h
    rx_clamped = max(0, min(rgb_w - 1, int(round(rx))))
    ry_clamped = max(0, min(rgb_h - 1, int(round(ry))))
    return rx_clamped, ry_clamped, in_view


def render_thermal_view(
    frame: ThermalFrame,
    hotspot: "Hotspot | None" = None,
    target_size: tuple[int, int] = (384, 288),
    colormap: int | None = None,
) -> "np.ndarray":
    """Render a ThermalFrame as a colormapped BGR image for cv2.imshow.

    Auto-scales contrast to the current frame's min/max so even a low
    dynamic-range scene looks readable. Marks the hotspot if given.
    """
    if cv2 is None:
        raise RuntimeError("OpenCV not available for thermal rendering")
    cmap = cv2.COLORMAP_INFERNO if colormap is None else colormap
    temps = frame.temps_c
    t_min = float(temps.min())
    t_max = float(temps.max())
    span = max(0.1, t_max - t_min)
    norm = ((temps - t_min) / span * 255.0).clip(0, 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cmap)
    out = cv2.resize(colored, target_size, interpolation=cv2.INTER_CUBIC)
    if hotspot is not None:
        # Use the actual frame shape (handles rotated frames correctly)
        th_h, th_w = temps.shape
        sx = target_size[0] / th_w
        sy = target_size[1] / th_h
        hx = int(hotspot.x * sx + sx / 2)
        hy = int(hotspot.y * sy + sy / 2)
        cv2.drawMarker(out, (hx, hy), (255, 255, 255), cv2.MARKER_CROSS, 22, 2)
        cv2.putText(out, f"{hotspot.temp_c:.1f}C",
                    (hx + 12, hy - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1)
    label = f"min {t_min:.1f}C  max {t_max:.1f}C"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(out, (5, 5), (15 + tw, 15 + th), (0, 0, 0), -1)
    cv2.putText(out, label, (10, 10 + th),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return out


def detect_hotspot(
    frame: ThermalFrame, threshold_c: float = 40.0
) -> Hotspot | None:
    """Return the single hottest pixel if it exceeds `threshold_c`, else None."""
    temps = frame.temps_c
    peak = float(temps.max())
    if peak < threshold_c:
        return None
    flat_idx = int(np.argmax(temps))
    y, x = np.unravel_index(flat_idx, temps.shape)
    area = int((temps > threshold_c).sum())
    return Hotspot(x=int(x), y=int(y), temp_c=peak, area_px=area)
