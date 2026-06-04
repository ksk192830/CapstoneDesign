"""HTTP client for esp32-p4 omni-wheel motor control (/control/manual)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class DriveVector:
    x: float = 0.0
    y: float = 0.0
    r: float = 0.0

    def normalized(self) -> DriveVector:
        m = max(1.0, abs(self.x), abs(self.y), abs(self.r))
        return DriveVector(self.x / m, self.y / m, self.r / m)

    def is_moving(self) -> bool:
        return abs(self.x) + abs(self.y) + abs(self.r) > 1e-3


class MotorHttpClient:
    """Polls /control/manual while moving; /control/stop when idle."""

    def __init__(self, base_url: str, ttl_ms: int = 300, period_s: float = 0.08):
        self._base = base_url.rstrip("/")
        self._ttl_ms = ttl_ms
        self._period_s = period_s
        self._lock = threading.Lock()
        self._vector = DriveVector()
        self._stop_sent = True
        self._last_error: str | None = None
        self._last_status: dict | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._fetch("/control/stop")
        except Exception:
            pass
        self._thread.join(timeout=2.0)

    def set_vector(self, x: float, y: float, r: float) -> None:
        with self._lock:
            self._vector = DriveVector(x, y, r)

    def set_pressed_keys(self, keys: set[str]) -> None:
        x = y = r = 0.0
        if "d" in keys:
            x += 1.0
        if "a" in keys:
            x -= 1.0
        if "w" in keys:
            y += 1.0
        if "s" in keys:
            y -= 1.0
        if "q" in keys:
            r += 1.0
        if "e" in keys:
            r -= 1.0
        self.set_vector(x, y, r)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_status(self) -> dict | None:
        return self._last_status

    def _fetch(self, path: str) -> bytes:
        req = urllib.request.Request(f"{self._base}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.read()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                vec = self._vector.normalized()
                moving = vec.is_moving()
            try:
                if moving:
                    url = (
                        f"/control/manual?x={vec.x:.2f}&y={vec.y:.2f}"
                        f"&r={vec.r:.2f}&ttl={self._ttl_ms}"
                    )
                    self._fetch(url)
                    self._stop_sent = False
                elif not self._stop_sent:
                    self._fetch("/control/stop")
                    self._stop_sent = True
                raw = self._fetch("/control/status")
                self._last_status = json.loads(raw.decode("utf-8"))
                self._last_error = None
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
                self._last_error = str(e)
            self._stop.wait(self._period_s)
