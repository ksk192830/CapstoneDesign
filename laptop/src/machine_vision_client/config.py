"""Shared laptop-side settings for the ESP32-P4 + heat-algorithm pipeline.

Override `ESP32_HOST` via environment variable when the board moves to a new
Wi-Fi network. Set `HEAT_LOCAL=1` for webcam + mock-thermal dev mode.
"""

from __future__ import annotations

import os
import sys

ESP32_HOST = os.environ.get("ESP32_HOST", "172.20.10.8")

# HTTP endpoints (firmware/esp32-p4-unified: camera on :80, thermal on :81)
VISIBLE_STREAM_URL = f"http://{ESP32_HOST}/stream.mjpg"
VISIBLE_JPEG_URL = f"http://{ESP32_HOST}/capture/visible.jpg"
THERMAL_FRAME_URL = f"http://{ESP32_HOST}:81/thermal/frame"
CONTROL_WS_URL = f"ws://{ESP32_HOST}/ws"

RGB_W = 640
RGB_H = 480
THERMAL_BAUD = 921600

# USB serial thermal fallback. On Windows set THERMAL_PORT=COM3 or edit below.
if sys.platform == "win32":
    THERMAL_PORT: str | None = os.environ.get("THERMAL_PORT") or None
else:
    THERMAL_PORT: str | None = os.environ.get("THERMAL_PORT") or "/dev/cu.usbmodem3101"

LOCAL_DEV = os.environ.get("HEAT_LOCAL", "").lower() in ("1", "true", "yes")

if LOCAL_DEV:
    RGB_SOURCE: int | str = 0
    THERMAL_HTTP_URL: str | None = None
    THERMAL_PORT = None
else:
    RGB_SOURCE: int | str = VISIBLE_STREAM_URL
    THERMAL_HTTP_URL: str | None = THERMAL_FRAME_URL
