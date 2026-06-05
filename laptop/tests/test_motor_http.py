"""Tests for the pure DriveVector helpers used by the motor transport."""

from machine_vision_client.control.motor_http import DriveVector


def test_is_moving_true_when_any_axis_nonzero():
    assert DriveVector(0.0, 0.0, 0.3).is_moving()
    assert DriveVector(1.0, 0.0, 0.0).is_moving()


def test_is_moving_false_when_effectively_zero():
    assert not DriveVector(0.0, 0.0, 0.0).is_moving()


def test_normalized_scales_down_oversized_vector():
    # Largest component is 2.0 -> divide all by 2.0 into the unit range.
    v = DriveVector(2.0, -1.0, 0.0).normalized()
    assert v.x == 1.0
    assert v.y == -0.5
    assert v.r == 0.0


def test_normalized_leaves_in_range_vector_unchanged():
    v = DriveVector(0.5, -0.5, 0.25).normalized()
    assert (v.x, v.y, v.r) == (0.5, -0.5, 0.25)
