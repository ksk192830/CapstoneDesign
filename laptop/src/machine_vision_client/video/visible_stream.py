"""Visible (RGB) camera source.

Handles three source kinds behind a cv2.VideoCapture-shaped interface:
  - int: local webcam via cv2.VideoCapture
  - URL ending .jpg/.jpeg: polled single-frame JPEG (HttpJpegSource) - plays
    nice with the ESP32-P4 single-task HTTP server
  - any other URL (.mjpg / RTSP / file): cv2.VideoCapture
"""

from __future__ import annotations

import time
import urllib.request

import cv2
import numpy as np

from machine_vision_client.config import RGB_H, RGB_SOURCE, RGB_W


class HttpJpegSource:
    """Polls a single-frame JPEG endpoint (e.g. /capture/visible.jpg).

    Mimics cv2.VideoCapture's `.read()` / `.isOpened()` / `.release()` so it
    slots in transparently. A long-lived MJPEG GET ties up the ESP32-P4's single
    HTTP server task forever, starving the thermal endpoint; short JPEG GETs
    return the server to its select() loop between frames.
    """

    def __init__(self, url: str, timeout: float = 2.0, min_period_s: float = 0.2):
        self.url = url
        self.timeout = timeout
        self.min_period_s = min_period_s
        self._last_request_at = 0.0
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                self._first_data = resp.read()
            self._opened = True
            self._last_request_at = time.time()
        except Exception as e:  # noqa: BLE001
            print(f"[rgb-jpeg] initial probe failed: {e}")
            self._first_data = None
            self._opened = False

    def isOpened(self) -> bool:  # noqa: N802 - cv2 API shape
        return self._opened

    def read(self):
        elapsed = time.time() - self._last_request_at
        if elapsed < self.min_period_s:
            time.sleep(self.min_period_s - elapsed)
        try:
            if self._first_data is not None:
                data = self._first_data
                self._first_data = None
            else:
                with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                    data = resp.read()
        except Exception:  # noqa: BLE001
            self._last_request_at = time.time()
            return False, None
        self._last_request_at = time.time()
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
    """Open `source` as a VideoCapture-shaped object (raises on failure)."""
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
    frame = np.full((h, w, 3), 32, dtype="uint8")
    (tw, th), _ = cv2.getTextSize(msg, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.putText(frame, msg, ((w - tw) // 2, (h + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return frame


class VisibleStream:
    """RGB source wrapper. `.read()` returns a BGR frame or None."""

    def __init__(self, source: int | str = RGB_SOURCE):
        self.source = source
        self._cap = None

    def open(self) -> bool:
        if self._cap is None:
            self._cap = open_rgb_capture(self.source)
        return self._cap.isOpened()

    def read(self):
        if self._cap is None:
            self.open()
        ok, frame = self._cap.read()
        return frame if ok else None

    def reopen(self) -> None:
        self.release()
        self._cap = open_rgb_capture(self.source)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
