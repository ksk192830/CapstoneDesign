import numpy as np

from machine_vision_client.ui.debug_viewer import DebugViewer


class _Risk:
    score = 0
    last_event = "idle"


def test_annotate_rgb_no_result_returns_same_shape():
    viewer = DebugViewer(materials={})
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = viewer.annotate_rgb(frame, None, _Risk(), 12.0)
    assert out.shape == (480, 640, 3)
    assert out.dtype == np.uint8
