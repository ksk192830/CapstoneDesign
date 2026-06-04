import numpy as np

from machine_vision_client.vision.pipeline import (
    aggregate_patches,
    crop_around,
    grid_for_density,
)


def test_grid_for_density_aspect_and_clamp():
    cols, rows = grid_for_density(4, 640, 480)
    assert cols == 4
    assert rows == 3  # round(4 * 480/640) == 3
    assert grid_for_density(99, 640, 480)[0] == 10  # clamped to MAX_DENSITY


def test_aggregate_patches_merges_same_label():
    patches = [
        {"x0": 0, "y0": 0, "x1": 10, "y1": 10, "label": "wood", "conf": 90.0, "peak_temp_c": 50.0},
        {"x0": 10, "y0": 0, "x1": 20, "y1": 10, "label": "wood", "conf": 80.0, "peak_temp_c": 60.0},
    ]
    regions = aggregate_patches(patches, cols=2, rows=1, min_conf=20.0)
    assert len(regions) == 1
    assert regions[0]["n_cells"] == 2
    assert regions[0]["peak_temp_c"] == 60.0


def test_aggregate_patches_drops_low_confidence():
    patches = [
        {"x0": 0, "y0": 0, "x1": 10, "y1": 10, "label": "wood", "conf": 5.0, "peak_temp_c": 50.0}
    ]
    assert aggregate_patches(patches, cols=1, rows=1, min_conf=20.0) == []


def test_crop_around_returns_requested_size():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    crop, _box = crop_around(frame, 50, 50, 40)
    assert crop.shape[:2] == (40, 40)
