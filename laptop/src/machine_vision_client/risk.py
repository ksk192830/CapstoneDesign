"""Risk-score aggregation following the flowchart.

Step 1: thermal hotspot detected -> +1 point.
Step 2 (flammable branch): +2, plus TTI-scaled bonus from dT/dt.
Step 2 (non-flammable branch): scan surroundings (TODO once full-frame
material map is wired up).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from machine_vision_client.materials import Material, ignition_threshold_c

# A temperature history is an ordered sequence of (timestamp_s, temp_c)
# samples — a RiskState deque or the ignition monitor's sample list.
TempHistory = Sequence[tuple[float, float]]


@dataclass
class TtiEstimate:
    seconds: float | None
    t_now_c: float
    t_ignite_c: float
    dt_per_s: float


def fit_rate_c_per_s(history: TempHistory) -> float:
    """Least-squares rise rate (degC/s) over (t, temp) samples.

    Robust to the frame-to-frame jitter MLX90640 produces, unlike a
    two-point (last-first)/dt slope that swings with noisy endpoints.
    Returns 0.0 for fewer than two samples or zero time spread.
    """
    n = len(history)
    if n < 2:
        return 0.0
    t0 = history[0][0]
    xs = [t - t0 for t, _ in history]
    ys = [temp for _, temp in history]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den <= 0:
        return 0.0
    return num / den


def estimate_tti(history: TempHistory, ignite_c: float) -> TtiEstimate:
    """Linear extrapolation TTI = (T_ignite - T_now) / (dT/dt), with the
    rate fitted by least squares over the whole history."""
    if not history:
        return TtiEstimate(None, 0.0, ignite_c, 0.0)
    t_now = history[-1][1]
    if len(history) < 2:
        return TtiEstimate(None, t_now, ignite_c, 0.0)
    rate = fit_rate_c_per_s(history)
    if t_now >= ignite_c:
        return TtiEstimate(0.0, t_now, ignite_c, rate)
    if rate <= 0:
        return TtiEstimate(None, t_now, ignite_c, rate)
    return TtiEstimate((ignite_c - t_now) / rate, t_now, ignite_c, rate)


def tti_points(tti_sec: float | None) -> int:
    if tti_sec is None:
        return 0
    if tti_sec <= 10:
        return 6
    if tti_sec <= 30:
        return 4
    if tti_sec <= 120:
        return 2
    return 1


@dataclass
class RiskState:
    score: int = 0
    last_event: str = "idle"
    last_tti: TtiEstimate | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=10))

    def update(self, hotspot_temp_c: float | None, material: Material | None) -> None:
        if hotspot_temp_c is None:
            self.last_event = "no heat source"
            self.last_tti = None
            return

        self.score += 1
        self.history.append((time.time(), float(hotspot_temp_c)))

        if material is None:
            self.last_event = f"heat source {hotspot_temp_c:.0f}C (no label)"
            self.last_tti = None
            return

        if not material.is_material:
            self.last_event = f"heat source {hotspot_temp_c:.0f}C ({material.label})"
            self.last_tti = None
            return

        if not material.flammable:
            self.last_event = f"non-flammable {material.label} at {hotspot_temp_c:.0f}C"
            self.last_tti = None
            return

        self.score += 2

        ignite_lo = ignition_threshold_c(material)
        if ignite_lo is None:
            self.last_event = f"flammable {material.label} (no AIT data)"
            self.last_tti = None
            return

        tti = estimate_tti(self.history, ignite_lo)
        self.last_tti = tti
        pts = tti_points(tti.seconds)
        self.score += pts

        if tti.seconds is None:
            self.last_event = f"{material.label}: warming ({hotspot_temp_c:.0f}/{ignite_lo:.0f}C)"
        elif tti.seconds == 0.0:
            self.last_event = f"{material.label}: AT IGNITION ({hotspot_temp_c:.0f}/{ignite_lo:.0f}C)"
        else:
            self.last_event = (
                f"{material.label}: TTI~{tti.seconds:.0f}s (+{pts}pt, "
                f"{hotspot_temp_c:.0f}/{ignite_lo:.0f}C)"
            )
