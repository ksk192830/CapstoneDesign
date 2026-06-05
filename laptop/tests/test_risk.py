"""Tests for the canonical fire-risk physics in risk.py.

The TTI engine is shared by RiskState (scoring) and the ignition-warning
monitor (UX), so its rate/extrapolation math is load-bearing and tested
directly.
"""

from collections import deque

import pytest

from machine_vision_client.materials import Material, ignition_threshold_c
from machine_vision_client.risk import (
    estimate_tti,
    fit_rate_c_per_s,
)


def _material(ignition_c):
    return Material(
        label="test",
        flammable=True,
        is_material=True,
        ignition_c=ignition_c,
        classification_raw="",
        note="",
    )


def test_ignition_threshold_uses_low_end_of_range():
    # Earliest plausible ignition = low end of the AIT range.
    assert ignition_threshold_c(_material((250.0, 300.0))) == 250.0


def test_ignition_threshold_none_without_data():
    assert ignition_threshold_c(_material(None)) is None
    assert ignition_threshold_c(None) is None


def _history(samples):
    return deque(samples)


def test_fit_rate_least_squares_ignores_endpoint_noise():
    # True trend rises 10 C/s, but the first/last samples are off-trend.
    # A two-point (last-first)/dt slope would read 6.25 C/s; least squares
    # recovers the underlying 7.0 C/s trend over all five samples.
    history = _history([(0.0, 30.0), (1.0, 30.0), (2.0, 40.0), (3.0, 50.0), (4.0, 55.0)])
    assert fit_rate_c_per_s(history) == pytest.approx(7.0)


def test_fit_rate_zero_for_single_sample():
    assert fit_rate_c_per_s(_history([(0.0, 42.0)])) == 0.0


def test_fit_rate_zero_for_no_time_spread():
    # All samples at the same instant -> undefined slope, must not divide by 0.
    assert fit_rate_c_per_s(_history([(2.0, 30.0), (2.0, 40.0)])) == 0.0


def test_estimate_tti_uses_least_squares_slope():
    # Same noisy history; ignite at 90 C, current temp 55 C.
    # eta = (90 - 55) / 7.0 == 5.0 s, using the least-squares rate.
    history = _history([(0.0, 30.0), (1.0, 30.0), (2.0, 40.0), (3.0, 50.0), (4.0, 55.0)])
    tti = estimate_tti(history, ignite_c=90.0)
    assert tti.dt_per_s == pytest.approx(7.0)
    assert tti.seconds == pytest.approx(5.0)


def test_estimate_tti_none_when_cooling():
    history = _history([(0.0, 80.0), (1.0, 70.0), (2.0, 60.0)])
    tti = estimate_tti(history, ignite_c=200.0)
    assert tti.seconds is None
    assert tti.dt_per_s < 0


def test_estimate_tti_zero_when_at_or_above_ignition():
    history = _history([(0.0, 240.0), (1.0, 250.0)])
    tti = estimate_tti(history, ignite_c=200.0)
    assert tti.seconds == 0.0
