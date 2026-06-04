"""Shared laptop-side settings for the ESP32-P4 + heat-algorithm pipeline.

Override `ESP32_HOST` via environment variable when the board moves to a new
Wi-Fi network. Set `HEAT_LOCAL=1` for webcam + mock-thermal dev mode.

Set `FIRMWARE_PROFILE=esp32-p4` when flashing firmware/esp32-p4 (car + camera +
thermal on swapped ports). Default `esp32-p4-unified` matches
firmware/esp32-p4-unified (camera :80, thermal :81, no wheel motors).
"""

from __future__ import annotations

import os
import sys

ESP32_HOST = os.environ.get("ESP32_HOST", "172.20.10.8")

# esp32-p4-unified | esp32-p4 (omni wheels + variable HTTP ports)
FIRMWARE_PROFILE = os.environ.get("FIRMWARE_PROFILE", "esp32-p4").strip().lower()

CONTROL_WS_URL = f"ws://{ESP32_HOST}/ws"
RGB_W = 640
RGB_H = 480
THERMAL_BAUD = 921600

if sys.platform == "win32":
    THERMAL_PORT: str | None = os.environ.get("THERMAL_PORT") or None
else:
    THERMAL_PORT: str | None = os.environ.get("THERMAL_PORT") or "/dev/cu.usbmodem3101"

LOCAL_DEV = os.environ.get("HEAT_LOCAL", "").lower() in ("1", "true", "yes")

_car_default = FIRMWARE_PROFILE == "esp32-p4" and not LOCAL_DEV
CAR_CONTROL_ENABLED = os.environ.get(
    "CAR_CONTROL", "1" if _car_default else "0"
).lower() in ("1", "true", "yes")

if FIRMWARE_PROFILE == "esp32-p4":
    # firmware/esp32-p4: stream :81, thermal + motor control :80
    VISIBLE_STREAM_URL = f"http://{ESP32_HOST}:81/stream.mjpg"
    VISIBLE_JPEG_URL = f"http://{ESP32_HOST}/capture/visible.jpg"
    THERMAL_FRAME_URL = f"http://{ESP32_HOST}/thermal/frame"
    MOTOR_BASE_URL = f"http://{ESP32_HOST}"
else:
    VISIBLE_STREAM_URL = f"http://{ESP32_HOST}/stream.mjpg"
    VISIBLE_JPEG_URL = f"http://{ESP32_HOST}/capture/visible.jpg"
    THERMAL_FRAME_URL = f"http://{ESP32_HOST}:81/thermal/frame"
    MOTOR_BASE_URL = f"http://{ESP32_HOST}"

if LOCAL_DEV:
    RGB_SOURCE: int | str = 0
    THERMAL_HTTP_URL: str | None = None
    THERMAL_PORT = None
    CAR_CONTROL_ENABLED = False
else:
    RGB_SOURCE: int | str = VISIBLE_STREAM_URL
    THERMAL_HTTP_URL: str | None = THERMAL_FRAME_URL
