"""Thermal camera source + physical alignment to the RGB camera.

Wraps the raw thermal source (HTTP -> USB serial -> mock, chosen from config)
and applies the fixed rotation / mirror / crop that aligns the MLX90640 with the
RGB camera, so callers receive frames already in RGB-aligned orientation. Also
exposes the effective dimensions + field-of-view needed to project thermal
pixels into RGB image space.
"""

from __future__ import annotations

import numpy as np

from machine_vision_client.config import (
    THERMAL_BAUD,
    THERMAL_HTTP_URL,
    THERMAL_PORT,
)
from machine_vision_client.thermal import (
    Esp32ThermalSource,
    HttpThermalSource,
    MockThermalSource,
    ThermalFrame,
    THERMAL_FOV_H_DEG,
    THERMAL_FOV_V_DEG,
    THERMAL_H,
    THERMAL_W,
)

# Counter-clockwise 90 deg rotations applied to each incoming thermal frame.
# Use this when the MLX90640 is physically mounted rotated relative to the RGB
# camera. 0 = none, 1 = CCW 90, 2 = 180, 3 = CW 90.
THERMAL_ROTATE_CCW: int = 1
# Horizontal mirror, applied after the rotation (MLX90640 reads rows
# back-to-front relative to the RGB camera's view).
THERMAL_MIRROR_H: bool = True
# Crop fractions applied after rotate + mirror: keep the top V_FRAC of rows and
# the left H_FRAC of columns. Used when the MLX90640 FOV is wider than the RGB
# camera. Set both to 1.0 to disable.
THERMAL_CROP_H_FRAC: float = 0.6
THERMAL_CROP_V_FRAC: float = 0.5


def _eff_dims_fov() -> tuple[int, int, float, float]:
    """Effective thermal width/height + FOV after rotation and crop.

    An odd number of 90 deg rotations swaps width<->height and H<->V FOV.
    """
    if THERMAL_ROTATE_CCW % 2 == 1:
        w, h = THERMAL_H, THERMAL_W
        fov_h, fov_v = THERMAL_FOV_V_DEG, THERMAL_FOV_H_DEG
    else:
        w, h = THERMAL_W, THERMAL_H
        fov_h, fov_v = THERMAL_FOV_H_DEG, THERMAL_FOV_V_DEG
    w = max(1, int(round(w * THERMAL_CROP_H_FRAC)))
    h = max(1, int(round(h * THERMAL_CROP_V_FRAC)))
    fov_h *= THERMAL_CROP_H_FRAC
    fov_v *= THERMAL_CROP_V_FRAC
    return w, h, fov_h, fov_v


EFF_THERMAL_W, EFF_THERMAL_H, EFF_THERMAL_FOV_H_DEG, EFF_THERMAL_FOV_V_DEG = _eff_dims_fov()


def align_frame(tframe: ThermalFrame) -> ThermalFrame:
    """Apply rotate -> mirror -> crop so the frame matches the RGB view."""
    temps = tframe.temps_c
    if THERMAL_ROTATE_CCW % 4 != 0:
        temps = np.rot90(temps, k=THERMAL_ROTATE_CCW)
    if THERMAL_MIRROR_H:
        temps = np.fliplr(temps)
    h, w = temps.shape
    new_h = max(1, int(round(h * THERMAL_CROP_V_FRAC)))
    new_w = max(1, int(round(w * THERMAL_CROP_H_FRAC)))
    if (new_h, new_w) != (h, w):
        temps = np.ascontiguousarray(temps[:new_h, :new_w])
    if temps is tframe.temps_c:
        return tframe
    return ThermalFrame(temps_c=temps, timestamp=tframe.timestamp)


def open_thermal_source():
    """Pick a thermal source: HTTP -> USB serial -> mock, per config."""
    if THERMAL_HTTP_URL:
        try:
            return HttpThermalSource(THERMAL_HTTP_URL)
        except Exception as e:  # noqa: BLE001 - fall back to mock on any failure
            print(f"[thermal] could not reach {THERMAL_HTTP_URL} ({e}); falling back to mock")
            return MockThermalSource()
    if THERMAL_PORT:
        try:
            return Esp32ThermalSource(THERMAL_PORT, THERMAL_BAUD)
        except Exception as e:  # noqa: BLE001
            print(f"[thermal] could not open {THERMAL_PORT} ({e}); falling back to mock")
            return MockThermalSource()
    return MockThermalSource()


class ThermalStream:
    """Yields aligned (rotated / mirrored / cropped) thermal frames."""

    eff_w: int = EFF_THERMAL_W
    eff_h: int = EFF_THERMAL_H
    eff_fov_h_deg: float = EFF_THERMAL_FOV_H_DEG
    eff_fov_v_deg: float = EFF_THERMAL_FOV_V_DEG

    def __init__(self, source=None):
        self._source = source if source is not None else open_thermal_source()

    def read(self) -> ThermalFrame:
        return align_frame(self._source.read())

    def proj_kwargs(self) -> dict:
        """Projection kwargs for thermal.project_thermal_to_rgb / tile_peak_temp_c."""
        return dict(
            thermal_w=self.eff_w,
            thermal_h=self.eff_h,
            thermal_fov_h_deg=self.eff_fov_h_deg,
            thermal_fov_v_deg=self.eff_fov_v_deg,
        )
