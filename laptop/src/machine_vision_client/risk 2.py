"""Risk-score aggregation following the flowchart.

Step 1: thermal hotspot detected -> +1 point.
Step 2 (flammable branch): +2, plus TTI-scaled bonus from dT/dt.
Step 2 (non-flammable branch): scan surroundings (TODO once full-frame
material map is wired up).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from materials import Material


@dataclass
class TtiEstimate:
    seconds: float | None
    t_now_c: float
    t_ignite_c: float
    dt_per_s: float


def estimate_tti(history: deque, ignite_c: float) -> TtiEstimate:
    """Linear extrapolation TTI = (T_ignite - T_now) / (dT/dt)."""
    if not history:
        return TtiEstimate(None, 0.0, ignite_c, 0.0)
    if len(history) < 2:
        return TtiEstimate(None, history[-1][1], ignite_c, 0.0)
    t0, T0 = history[0]
    t1, T1 = history[-1]
    dt = t1 - t0
    if dt <= 0:
        return TtiEstimate(None, T1, ignite_c, 0.0)
    rate = (T1 - T0) / dt
    if T1 >= ignite_c:
        return TtiEstimate(0.0, T1, ignite_c, rate)
    if rate <= 0:
        return TtiEstimate(None, T1, ignite_c, rate)
    return TtiEstimate((ignite_c - T1) / rate, T1, ignite_c, rate)


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

        if material.ignition_c is None:
            self.last_event = f"flammable {material.label} (no AIT data)"
            self.last_tti = None
            return

        ignite_lo = material.ignition_c[0]
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
