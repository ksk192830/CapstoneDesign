"""Behavioural tests for the ignition-warning state machine.

These pin the phase transitions so the monitor can be refactored to
delegate its physics to risk.estimate_tti without changing behaviour.
The monitor is pure state — no rendering is exercised here.
"""

from types import SimpleNamespace

from machine_vision_client.ignition_warning import (
    ALERT_HOLD_S,
    ARM_THRESHOLD_C,
    COOLDOWN_RESET_S,
    Phase,
    IgnitionTrendMonitor,
)
from machine_vision_client.materials import Material


def _hot(temp_c):
    return SimpleNamespace(temp_c=temp_c)


def _material(ignition_c):
    return Material(
        label="wood",
        flammable=True,
        is_material=True,
        ignition_c=ignition_c,
        classification_raw="",
        note="",
    )


def _feed(monitor, mat, series):
    """Feed (t, temp) samples; return the monitor for chaining."""
    for t, temp in series:
        monitor.update(_hot(temp), mat, now=t)
    return monitor


def test_first_hot_sample_arms_measuring():
    m = IgnitionTrendMonitor()
    m.update(_hot(ARM_THRESHOLD_C + 5), _material((250.0, 300.0)), now=0.0)
    assert m.phase is Phase.MEASURING


def test_rising_within_horizon_warns():
    m = _feed(
        IgnitionTrendMonitor(),
        _material((250.0, 300.0)),
        [(0.0, 100.0), (2.0, 120.0), (4.0, 140.0), (6.0, 160.0)],
    )
    assert m.phase is Phase.WARNING
    assert m.eta_to_ait_s is not None and m.eta_to_ait_s > 0
    assert m.rise_rate_c_per_s > 0


def test_cooling_is_safe():
    m = _feed(
        IgnitionTrendMonitor(),
        _material((600.0, 700.0)),
        [(0.0, 200.0), (2.0, 180.0), (4.0, 160.0), (6.0, 140.0)],
    )
    assert m.phase is Phase.SAFE
    assert m.rise_rate_c_per_s < 0


def test_flat_is_monitoring():
    m = _feed(
        IgnitionTrendMonitor(),
        _material((250.0, 300.0)),
        [(0.0, 100.0), (2.0, 100.0), (4.0, 100.0), (6.0, 100.0)],
    )
    assert m.phase is Phase.MONITORING


def test_at_or_above_ignition_warns_immediately():
    m = _feed(
        IgnitionTrendMonitor(),
        _material((250.0, 300.0)),
        [(0.0, 260.0), (2.0, 262.0), (4.0, 261.0), (6.0, 263.0)],
    )
    assert m.phase is Phase.WARNING
    assert m.eta_to_ait_s == 0.0


def test_hotspot_gone_past_cooldown_resets_to_idle():
    m = IgnitionTrendMonitor()
    m.update(_hot(ARM_THRESHOLD_C + 5), _material((250.0, 300.0)), now=0.0)
    assert m.phase is Phase.MEASURING
    m.update(None, None, now=COOLDOWN_RESET_S + 1.0)
    assert m.phase is Phase.IDLE


def test_alert_phase_held_for_minimum_time():
    """A shown alert (here WARNING/red) must not flicker away before
    ALERT_HOLD_S, even when the rolling fit would already imply SAFE."""
    m = IgnitionTrendMonitor()
    m.ait_c = 250.0
    m.phase = Phase.WARNING
    m.phase_since = 10.0
    # Cooling samples that on their own would map to SAFE.
    m.samples = [(10.0, 200.0), (11.0, 180.0), (12.0, 160.0), (13.0, 140.0)]

    # Within the hold window -> WARNING stays on screen.
    m._evaluate(140.0, 10.0 + ALERT_HOLD_S - 0.5)
    assert m.phase is Phase.WARNING

    # Past the hold window -> free to fall back to SAFE.
    m._evaluate(140.0, 10.0 + ALERT_HOLD_S + 0.1)
    assert m.phase is Phase.SAFE


def test_alert_hold_never_delays_escalation_to_warning():
    """Even mid-hold on a green SAFE alert, crossing the ignition
    threshold escalates to WARNING immediately (safety overrides the hold)."""
    m = IgnitionTrendMonitor()
    m.ait_c = 250.0
    m.phase = Phase.SAFE
    m.phase_since = 10.0
    m.samples = [(10.0, 240.0), (10.3, 250.0), (10.6, 258.0), (10.9, 260.0)]

    m._evaluate(260.0, 10.0 + 0.9)  # well within the hold window
    assert m.phase is Phase.WARNING


def test_measure_remaining_counts_down():
    m = IgnitionTrendMonitor()
    m.update(_hot(ARM_THRESHOLD_C + 5), _material((250.0, 300.0)), now=10.0)
    # 1s into a 5s window -> ~4s remaining, no wall-clock involved.
    assert m.measure_remaining_s(11.0) > 0
    assert m.measure_remaining_s(99.0) == 0.0
