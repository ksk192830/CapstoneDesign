import numpy as np

from machine_vision_client.ignition_warning import IgnitionTrendMonitor, Phase
from machine_vision_client.ui.debug_viewer import DebugViewer, draw_ignition_overlay


class _Risk:
    score = 0
    last_event = "idle"


def test_annotate_rgb_no_result_returns_same_shape():
    viewer = DebugViewer(materials={})
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = viewer.annotate_rgb(frame, None, _Risk(), 12.0)
    assert out.shape == (480, 640, 3)
    assert out.dtype == np.uint8


def test_draw_ignition_overlay_idle_leaves_frame_untouched():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    monitor = IgnitionTrendMonitor()  # IDLE
    draw_ignition_overlay(frame, monitor, now=0.0)
    assert frame.sum() == 0  # no popup drawn when idle


def test_draw_ignition_overlay_warning_paints_pixels():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    monitor = IgnitionTrendMonitor(
        phase=Phase.WARNING,
        eta_to_ait_s=120.0,
        rise_rate_c_per_s=0.5,
        ait_c=250.0,
        material_label="wood",
    )
    draw_ignition_overlay(frame, monitor, now=0.0)
    assert frame.sum() > 0  # the red warning box was drawn
