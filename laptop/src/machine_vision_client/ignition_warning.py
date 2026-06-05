"""Trend-based ignition-risk early warning state machine.

Design rationale (see project report):
  * A high-temperature hotspot triggers a short measurement window.
  * During the window the MAIN LOOP IS NOT BLOCKED — we keep reading
    thermal frames so we can sample the temperature several times.
  * From the samples we fit a line (least squares) to get a robust
    rise-rate (degC/s) instead of a noisy (last-first)/dt slope.
  * We linearly extrapolate to the material's autoignition temperature
    (AIT). Because short-window linear extrapolation over a long
    horizon is uncertain (heat loss makes real curves sub-linear, AIT
    itself is a range, MLX90640 has emissivity/abs-temp error), we
    deliberately present the result as a TREND-BASED WARNING ("on the
    current trend, ignition risk within ~N min"), NOT a precise
    countdown.

This module owns only the STATE MACHINE. The rate/TTI physics lives in
`risk.py` (shared with the risk score, single source of truth) and the
overlay rendering lives in `ui/debug_viewer.py` (the canonical UI layer).

Usage (in the main loop, once per frame):

    from machine_vision_client.ignition_warning import IgnitionTrendMonitor
    from machine_vision_client.ui.debug_viewer import draw_ignition_overlay

    monitor = IgnitionTrendMonitor()           # before the loop
    ...
    # inside the loop, after live_hotspot / mat are known:
    monitor.update(live_hotspot, mat, now)
    draw_ignition_overlay(frame, monitor, now)  # debug_viewer renders it

The monitor never sleeps and never touches OpenCV.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from machine_vision_client.materials import ignition_threshold_c
from machine_vision_client.risk import estimate_tti

# ---- tuning knobs -------------------------------------------------------

# A hotspot at/above this temperature arms the monitor. Kept separate
# from the vision layer's HOTSPOT_THRESHOLD_C so the warning can be more
# conservative than mere hotspot detection if desired.
ARM_THRESHOLD_C: float = 45.0

# Length of the measurement window, in seconds.
MEASURE_WINDOW_S: float = 5.0

# Minimum samples needed before we trust a fitted slope.
MIN_SAMPLES: int = 4

# Prediction horizon. If the trend says AIT is reached within this many
# seconds, raise the warning.
HORIZON_S: float = 600.0  # 10 minutes

# A rise-rate below this (degC/s) is treated as "not really rising":
# avoids predicting ignition from sensor jitter.
MIN_RISE_RATE_C_PER_S: float = 0.02

# If the hotspot disappears (drops below ARM_THRESHOLD_C) for this long,
# reset the whole state machine back to idle.
COOLDOWN_RESET_S: float = 3.0

# Fallback AIT (degC) used only when the identified material has no
# ignition data. Conservative low end of common combustibles.
FALLBACK_AIT_C: float = 250.0


class Phase(Enum):
    IDLE = 0          # no qualifying hotspot
    MEASURING = 1     # window open, collecting samples
    WARNING = 2       # trend predicts ignition within horizon -> DISPATCH NOW
    MONITORING = 3    # rising, but ignition not within horizon (keep watching)
    SAFE = 4          # temperature falling (negative rate) -> OK to proceed


@dataclass
class IgnitionTrendMonitor:
    phase: Phase = Phase.IDLE
    samples: list = field(default_factory=list)   # (t, temp_c) tuples
    window_start: float = 0.0
    last_seen_hot: float = 0.0

    # Last computed results (for the renderer / external use).
    rise_rate_c_per_s: float = 0.0
    eta_to_ait_s: Optional[float] = None
    ait_c: Optional[float] = None
    material_label: str = ""

    def _reset(self) -> None:
        self.phase = Phase.IDLE
        self.samples = []
        self.window_start = 0.0
        self.rise_rate_c_per_s = 0.0
        self.eta_to_ait_s = None
        self.ait_c = None
        self.material_label = ""

    def update(self, hotspot, mat, now: Optional[float] = None) -> None:
        """Call once per frame. `hotspot` is the live Hotspot (or None),
        `mat` is the identified Material (or None). Never blocks."""
        if now is None:
            now = time.time()

        hot = hotspot is not None and hotspot.temp_c >= ARM_THRESHOLD_C

        # Hotspot gone long enough -> reset.
        if not hot:
            if self.phase != Phase.IDLE and (now - self.last_seen_hot) > COOLDOWN_RESET_S:
                self._reset()
            return

        self.last_seen_hot = now
        temp = float(hotspot.temp_c)

        if self.phase == Phase.IDLE:
            # Arm: open a fresh measurement window.
            self.phase = Phase.MEASURING
            self.window_start = now
            self.samples = [(now, temp)]
            self.ait_c = ignition_threshold_c(mat)
            self.material_label = getattr(mat, "label", "") or ""
            return

        if self.phase == Phase.MEASURING:
            self.samples.append((now, temp))
            # keep AIT/material fresh if it was unknown at arm time
            if self.ait_c is None:
                self.ait_c = ignition_threshold_c(mat)
            if not self.material_label:
                self.material_label = getattr(mat, "label", "") or ""

            if (now - self.window_start) >= MEASURE_WINDOW_S and len(self.samples) >= MIN_SAMPLES:
                self._evaluate(temp)
            return

        # In WARNING / MONITORING / SAFE: keep refreshing the estimate on a
        # rolling window so the warning can clear or escalate.
        self.samples.append((now, temp))
        cutoff = now - MEASURE_WINDOW_S
        recent = [s for s in self.samples if s[0] >= cutoff]
        self.samples = recent if len(recent) >= MIN_SAMPLES else self.samples[-MIN_SAMPLES:]
        if len(self.samples) >= MIN_SAMPLES:
            self._evaluate(temp)

    def _evaluate(self, current_temp: float) -> None:
        """Map the canonical TTI estimate onto a UX phase. All physics
        (least-squares rate, linear extrapolation) comes from
        risk.estimate_tti; this method only owns the UX thresholds."""
        ait = self.ait_c if self.ait_c is not None else FALLBACK_AIT_C
        tti = estimate_tti(self.samples, ait)
        rate = tti.dt_per_s
        self.rise_rate_c_per_s = rate

        # Already at/above AIT -> immediate warning regardless of slope.
        if current_temp >= ait:
            self.eta_to_ait_s = 0.0
            self.phase = Phase.WARNING
            return

        # Falling (negative rate) -> cooling down, safe to proceed.
        if rate <= -MIN_RISE_RATE_C_PER_S:
            self.eta_to_ait_s = None
            self.phase = Phase.SAFE
            return

        # Near-flat (within +/- noise band): not meaningfully changing.
        if rate < MIN_RISE_RATE_C_PER_S:
            self.eta_to_ait_s = None
            self.phase = Phase.MONITORING
            return

        # Rising -> use the extrapolated TTI; alarm if within horizon.
        self.eta_to_ait_s = tti.seconds
        if tti.seconds is not None and 0 < tti.seconds <= HORIZON_S:
            self.phase = Phase.WARNING       # within horizon -> DISPATCH NOW
        else:
            self.phase = Phase.MONITORING    # rising but still far off

    def measure_remaining_s(self, now: float) -> float:
        """Seconds left in the measurement window (0 once elapsed)."""
        return max(0.0, MEASURE_WINDOW_S - (now - self.window_start))

    def status_line(self) -> str:
        """One-line status for console logging / format_status."""
        if self.phase == Phase.IDLE:
            return "ign=idle"
        if self.phase == Phase.MEASURING:
            return f"ign=measuring({len(self.samples)})"
        rate_min = self.rise_rate_c_per_s * 60.0
        if self.phase == Phase.SAFE:
            return f"ign=SAFE cooling={abs(rate_min):0.1f}C/min ok-to-go"
        if self.phase == Phase.WARNING:
            eta = self.eta_to_ait_s or 0.0
            return f"ign=WARN eta={eta/60:0.1f}min DISPATCH rise={rate_min:0.1f}C/min"
        return f"ign=watch rise={rate_min:0.1f}C/min"
