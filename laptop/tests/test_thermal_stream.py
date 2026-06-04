import numpy as np

from machine_vision_client.thermal import ThermalFrame
from machine_vision_client.video.thermal_stream import ThermalStream, align_frame


def test_align_frame_rotates_and_crops():
    # Raw MLX90640 frame is (H=24, W=32). rotate CCW once -> (32, 24);
    # crop V_FRAC=0.5 rows -> 16, H_FRAC=0.6 cols -> round(14.4)=14.
    temps = np.arange(24 * 32, dtype=np.float32).reshape(24, 32)
    out = align_frame(ThermalFrame(temps_c=temps, timestamp=0.0))
    assert out.temps_c.shape == (16, 14)


def test_eff_dims_match_aligned_shape():
    assert (ThermalStream.eff_h, ThermalStream.eff_w) == (16, 14)


def test_read_applies_alignment():
    class FakeSource:
        def read(self):
            return ThermalFrame(
                temps_c=np.zeros((24, 32), dtype=np.float32), timestamp=0.0
            )

    stream = ThermalStream(source=FakeSource())
    assert stream.read().temps_c.shape == (16, 14)


def test_proj_kwargs_keys():
    kw = ThermalStream(source=type("S", (), {"read": lambda self: None})()).proj_kwargs()
    assert set(kw) == {"thermal_w", "thermal_h", "thermal_fov_h_deg", "thermal_fov_v_deg"}
    assert kw["thermal_w"] == 14 and kw["thermal_h"] == 16
