"""Shared laptop-side settings for the ESP32-P4 heat-algorithm pipeline.

Override `ESP32_HOST` via environment variable when the board moves to a new
Wi-Fi network. Set `HEAT_LOCAL=1` for webcam + mock-thermal dev mode.

Endpoints match firmware/esp32-p4-unified: camera MJPEG on :80, thermal on :81.
The heat algorithm is served as a web UI at WEB_HOST:WEB_PORT.
"""

from __future__ import annotations

import os
import sys

ESP32_HOST = os.environ.get("ESP32_HOST", "172.20.10.8")

# HTTP endpoints for firmware/esp32-p4 (camera + thermal + motor on one board):
#   port 81 -> MJPEG camera stream (/stream.mjpg)
#   port 80 -> still JPEG, thermal frame, and /control/* motor endpoints
# (firmware/esp32-p4-unified uses the opposite split: camera :80, thermal :81.)
VISIBLE_STREAM_URL = f"http://{ESP32_HOST}:81/stream.mjpg"
VISIBLE_JPEG_URL = f"http://{ESP32_HOST}/capture/visible.jpg"
THERMAL_FRAME_URL = f"http://{ESP32_HOST}/thermal/frame"

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

# Motor control host. Defaults to the camera/thermal board (ESP32_HOST) so
# the laptop assumes the one-board end state; override with MOTOR_HOST while
# motors live on a separate board.
MOTOR_HOST = os.environ.get("MOTOR_HOST", ESP32_HOST)
MOTOR_BASE_URL = f"http://{MOTOR_HOST}"

# Heat web interface (browser-viewable on the LAN).
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "8000"))
