"""OpenCV drive panel — virtual stick + on-screen WASD/QE (hold to drive)."""

from __future__ import annotations

import os

import cv2
import numpy as np

from machine_vision_client.control.motor_http import MotorHttpClient, DriveVector

CAR_WIN = f"Car Control [pid {os.getpid()}]"

PANEL_W, PANEL_H = 480, 420
JOY_CX, JOY_CY = PANEL_W // 2, 160
JOY_R = 90

# (label, x0, y0, x1, y1, key)
_BUTTONS = [
    ("W", 200, 280, 280, 330, "w"),
    ("A", 120, 330, 200, 380, "a"),
    ("S", 200, 330, 280, 380, "s"),
    ("D", 280, 330, 360, 380, "d"),
    ("Q", 60, 330, 120, 380, "q"),
    ("E", 360, 330, 420, 380, "e"),
]


def _hit_button(x: int, y: int) -> str | None:
    for _label, x0, y0, x1, y1, key in _BUTTONS:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return key
    return None


class DrivePanel:
    def __init__(self, motor: MotorHttpClient):
        self._motor = motor
        self._pressed: set[str] = set()
        self._joy_xy = (0.0, 0.0)
        self._joy_drag = False
        self._mouse_on_button: str | None = None
        cv2.namedWindow(CAR_WIN, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(CAR_WIN, self._on_mouse)

    def start(self) -> None:
        self._motor.start()

    def stop(self) -> None:
        self._motor.set_vector(0, 0, 0)
        self._motor.stop()

    def handle_key(self, key: int) -> bool:
        """Return True if key was consumed by drive controls."""
        if key == 255 or key == 0xFF:
            return False
        ch = chr(key).lower()
        if ch == " ":
            self._pressed.clear()
            self._joy_xy = (0.0, 0.0)
            self._sync_vector()
            return True
        if ch in "weasd":
            self._pressed.add(ch)
            self._sync_vector()
            return True
        return False

    def render(self) -> None:
        panel = np.full((PANEL_H, PANEL_W, 3), 28, dtype=np.uint8)

        cv2.putText(panel, "CAR CONTROL", (12, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2, cv2.LINE_AA)
        cv2.putText(panel, "Drag stick or hold WASD/QE  |  Space=stop  |  Esc=quit app",
                    (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 160, 160), 1, cv2.LINE_AA)

        cv2.circle(panel, (JOY_CX, JOY_CY), JOY_R, (60, 60, 60), 2)
        cv2.circle(panel, (JOY_CX, JOY_CY), 4, (100, 100, 100), -1)
        jx = int(JOY_CX + self._joy_xy[0] * (JOY_R - 8))
        jy = int(JOY_CY - self._joy_xy[1] * (JOY_R - 8))
        cv2.circle(panel, (jx, jy), 14, (80, 200, 255), -1)
        cv2.circle(panel, (jx, jy), 14, (255, 255, 255), 2)

        for label, x0, y0, x1, y1, key in _BUTTONS:
            active = key in self._pressed
            color = (60, 180, 60) if active else (70, 70, 70)
            cv2.rectangle(panel, (x0, y0), (x1, y1), color, -1)
            cv2.rectangle(panel, (x0, y0), (x1, y1), (200, 200, 200), 1)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.putText(panel, label,
                        (x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 + th) // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        vec = self._current_vector()
        cv2.putText(panel, f"drive  x={vec.x:+.2f}  y={vec.y:+.2f}  r={vec.r:+.2f}",
                    (12, 400), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 255, 200), 1, cv2.LINE_AA)

        st = self._motor.last_status
        err = self._motor.last_error
        if err:
            cv2.putText(panel, f"error: {err[:52]}", (12, 88),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 80, 255), 1, cv2.LINE_AA)
        elif st:
            line = (
                f"motors  active={st.get('active')}  "
                f"wheels FL/FR/BL/BR: {st.get('wheels', {}).get('fl', 0):.2f}/"
                f"{st.get('wheels', {}).get('fr', 0):.2f}/"
                f"{st.get('wheels', {}).get('bl', 0):.2f}/"
                f"{st.get('wheels', {}).get('br', 0):.2f}"
            )
            cv2.putText(panel, line[:70], (12, 88),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 220, 255), 1, cv2.LINE_AA)

        cv2.imshow(CAR_WIN, panel)

    def _current_vector(self) -> DriveVector:
        x = y = r = 0.0
        if "d" in self._pressed:
            x += 1.0
        if "a" in self._pressed:
            x -= 1.0
        if "w" in self._pressed:
            y += 1.0
        if "s" in self._pressed:
            y -= 1.0
        if "q" in self._pressed:
            r += 1.0
        if "e" in self._pressed:
            r -= 1.0
        x += self._joy_xy[0]
        y += self._joy_xy[1]
        return DriveVector(x, y, r).normalized()

    def _sync_vector(self) -> None:
        v = self._current_vector()
        self._motor.set_vector(v.x, v.y, v.r)

    def _on_mouse(self, event, x, y, _flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            key = _hit_button(x, y)
            if key:
                self._mouse_on_button = key
                self._pressed.add(key)
            else:
                dx = x - JOY_CX
                dy = JOY_CY - y
                dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
                scale = min(1.0, (JOY_R - 8) / dist)
                self._joy_xy = (dx * scale / (JOY_R - 8), dy * scale / (JOY_R - 8))
                self._joy_drag = True
            self._sync_vector()
        elif event == cv2.EVENT_MOUSEMOVE and self._joy_drag:
            dx = x - JOY_CX
            dy = JOY_CY - y
            dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
            scale = min(1.0, (JOY_R - 8) / dist)
            self._joy_xy = (dx * scale / (JOY_R - 8), dy * scale / (JOY_R - 8))
            self._sync_vector()
        elif event == cv2.EVENT_LBUTTONUP:
            if self._mouse_on_button:
                self._pressed.discard(self._mouse_on_button)
                self._mouse_on_button = None
            self._joy_drag = False
            self._joy_xy = (0.0, 0.0)
            self._sync_vector()
