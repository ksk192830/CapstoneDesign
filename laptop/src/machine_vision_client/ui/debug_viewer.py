"""Frame annotation for the heat algorithm (drawing only - no windows).

`DebugViewer.annotate_rgb` composites the material-grid overlay + risk HUD +
hotspot crosshair onto a live RGB frame; `render_thermal` colormaps the cropped
thermal frame. Both return `np.ndarray` images for the web server to JPEG-encode.
"""

from __future__ import annotations

import cv2

from machine_vision_client.ignition_warning import HORIZON_S, MIN_RISE_RATE_C_PER_S, Phase
from machine_vision_client.thermal import render_thermal_view

WARM_THRESHOLD_C = 35.0   # below this, a tile is treated as ambient (gray)


def _is_nan(x) -> bool:
    return x is None or x != x


def _region_color(material, peak_temp_c) -> tuple[int, int, int]:
    """BGR fill color for a region tile, tiered by its own peak temperature."""
    if material is None or not material.is_material:
        return (130, 130, 130)
    if _is_nan(peak_temp_c) or peak_temp_c < WARM_THRESHOLD_C:
        return (130, 130, 130)
    if material.flammable and material.ignition_c is not None:
        ait_lo = material.ignition_c[0]
        frac = (peak_temp_c / ait_lo) if ait_lo > 0 else 0.0
        if frac < 0.5:
            return (60, 200, 60)
        if frac < 0.75:
            return (40, 220, 220)
        if frac < 1.0:
            return (40, 140, 240)
        return (40, 40, 240)
    t = peak_temp_c
    if t < 50:
        return (60, 200, 60)
    if t < 100:
        return (40, 220, 220)
    if t < 200:
        return (40, 140, 240)
    return (40, 40, 240)


def _font_scale_for_cell(cell_w: int, cell_h: int) -> float:
    s = min(cell_w, cell_h)
    if s >= 180:
        return 0.55
    if s >= 130:
        return 0.45
    if s >= 90:
        return 0.38
    return 0.32


def draw_regions(frame, regions, materials, alpha: float = 0.22):
    """Translucent fill per cell + one inset top-left label per region."""
    if not regions:
        return

    overlay = frame.copy()
    for r in regions:
        color = _region_color(materials.get(r["label"]), r.get("peak_temp_c"))
        for x0, y0, x1, y1 in r["cell_boxes"]:
            cv2.rectangle(overlay, (x0, y0), (x1, y1), color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)

    for r in regions:
        color = _region_color(materials.get(r["label"]), r.get("peak_temp_c"))
        cx0, cy0, cx1, cy1 = r["cell_boxes"][0]
        scale = _font_scale_for_cell(cx1 - cx0, cy1 - cy0)
        text = f"{r['label']} {r['avg_conf']:.0f}%"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        tx = r["x0"] + 4
        ty = r["y0"] + th + 4
        cv2.rectangle(frame, (tx - 2, ty - th - 2), (tx + tw + 2, ty + 2), (0, 0, 0), -1)
        cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1)


def risk_color_bgr(score: int) -> tuple[int, int, int]:
    """Tiered color for the risk score: gray / green / yellow / orange / red."""
    if score <= 0:
        return (180, 180, 180)
    if score < 5:
        return (60, 200, 60)
    if score < 15:
        return (40, 220, 220)
    if score < 30:
        return (40, 140, 240)
    return (40, 40, 240)


def draw_hud(frame, risk, hotspot, hotspot_rgb_xy, mat, fps):
    """Top-left panel + on-image hotspot crosshair."""
    h, w = frame.shape[:2]

    if hotspot is not None and hotspot_rgb_xy is not None:
        rx, ry = hotspot_rgb_xy
        cv2.drawMarker(frame, (rx, ry), (255, 255, 255), cv2.MARKER_CROSS, 30, 2)
        cv2.drawMarker(frame, (rx, ry), (0, 0, 0), cv2.MARKER_CROSS, 28, 1)
        tag = f"{hotspot.temp_c:.0f}C"
        (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        tx = max(0, min(w - tw - 6, rx + 18))
        ty = max(th + 6, ry - 10)
        cv2.rectangle(frame, (tx - 4, ty - th - 4), (tx + tw + 4, ty + 4), (0, 0, 0), -1)
        cv2.putText(frame, tag, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

    panel_w = min(380, w)
    panel_h = 110
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, dst=frame)

    score = int(risk.score)
    cv2.putText(frame, f"RISK {score}", (10, 42),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, risk_color_bgr(score), 3, cv2.LINE_AA)

    event = (risk.last_event or "idle")[:46]
    cv2.putText(frame, event, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 255, 255) if score > 0 else (200, 200, 200), 1, cv2.LINE_AA)

    if hotspot is not None:
        line = f"hotspot {hotspot.temp_c:.0f}C"
        if mat is not None and mat.is_material:
            line += f"  ->  {mat.label}"
            if mat.ignition_c is not None:
                line += f" (AIT {mat.ignition_c[0]:.0f}-{mat.ignition_c[1]:.0f}C)"
            elif not mat.flammable:
                line += " (non-flam)"
        elif mat is not None:
            line += f"  ->  {mat.label} (n/a)"
    else:
        line = "no heat source"
    cv2.putText(frame, line[:50], (10, 92),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)

    cv2.putText(frame, f"{fps:.1f} fps", (10, panel_h - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 160), 1, cv2.LINE_AA)


def format_status(fps, hotspot, label, conf, mat, risk, grid_cols, grid_rows) -> str:
    hs = (f"hotspot={hotspot.temp_c:.1f}C@({hotspot.x},{hotspot.y})"
          if hotspot is not None else "hotspot=none")
    if mat is not None and mat.ignition_c is not None:
        ait = f"  AIT={mat.ignition_c[0]:.0f}-{mat.ignition_c[1]:.0f}C"
    else:
        ait = ""
    matstr = f"  material={label} {conf:.0f}%" if label else ""
    return (f"fps={fps:4.1f}  grid={grid_cols}x{grid_rows}  {hs}{matstr}{ait}"
            f"  risk={risk.score}  [{risk.last_event}]")


class DebugViewer:
    """Draws the heat overlay + HUD onto frames; returns annotated images."""

    def __init__(self, materials):
        self._materials = materials

    def annotate_rgb(self, frame, result, risk, fps):
        """Draw region overlay + HUD onto `frame` in place; return it."""
        regions = result.regions if result is not None else []
        hotspot = result.hotspot if result is not None else None
        hotspot_rgb_xy = result.hotspot_rgb_xy if result is not None else None
        mat = result.mat if result is not None else None
        draw_regions(frame, regions, self._materials)
        draw_hud(frame, risk, hotspot, hotspot_rgb_xy, mat, fps)
        return frame

    def render_thermal(self, tframe, live_hotspot):
        return render_thermal_view(tframe, live_hotspot)


def _overlay_box(frame, lines, color, anchor="center"):
    """Translucent boxed text popup, centered or top-anchored."""
    h, w = frame.shape[:2]
    pad = 16
    font = cv2.FONT_HERSHEY_SIMPLEX
    scales = [0.9] + [0.6] * (len(lines) - 1)
    sizes = [cv2.getTextSize(t, font, s, 2)[0] for t, s in zip(lines, scales)]
    box_w = max(tw for tw, _ in sizes) + pad * 2
    line_h = max(th for _, th in sizes) + 12
    box_h = line_h * len(lines) + pad
    x0 = max(0, (w - box_w) // 2)
    y0 = max(0, (h - box_h) // 2 if anchor == "center" else 20)
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, dst=frame)
    cv2.rectangle(frame, (x0, y0), (x0 + box_w, y0 + box_h), color, 2)
    y = y0 + pad + sizes[0][1]
    for txt, scale in zip(lines, scales):
        cv2.putText(frame, txt, (x0 + pad, y), font, scale, color, 2, cv2.LINE_AA)
        y += line_h


def draw_ignition_overlay(frame, monitor, now: float) -> None:
    """Render the ignition-warning popup for the monitor's current phase.

    The monitor is pure state; all OpenCV drawing for the alert lives
    here in the UI layer. IDLE draws nothing (the HUD already shows
    ongoing risk)."""
    phase = monitor.phase
    if phase is Phase.MEASURING:
        remain = monitor.measure_remaining_s(now)
        _overlay_box(
            frame,
            ["HOLD - MEASURING HEAT TREND",
             f"Sampling temperature... {remain:0.1f}s",
             "Please keep the source steady."],
            (40, 200, 255),  # amber (BGR)
        )
    elif phase is Phase.WARNING:
        eta = monitor.eta_to_ait_s or 0.0
        mat = monitor.material_label or "material"
        ait_txt = f"{monitor.ait_c:.0f}C" if monitor.ait_c is not None else "ignition temp"
        if eta <= 0:
            head, eta_line = "WARNING: AT IGNITION-RISK TEMPERATURE", "Already at/above ignition threshold"
        else:
            head = "WARNING: IGNITION RISK"
            eta_line = f"Estimated time to ignition: ~{eta / 60:0.1f} min  ({ait_txt})"
        _overlay_box(
            frame,
            [head,
             eta_line,
             ">> DISPATCH NOW - respond immediately <<",
             f"{mat}  |  rise {monitor.rise_rate_c_per_s * 60:0.1f} C/min",
             "Trend estimate - not a precise countdown"],
            (40, 40, 240),  # red (BGR)
        )
    elif phase is Phase.SAFE:
        _overlay_box(
            frame,
            ["SAFE - TEMPERATURE FALLING",
             "No ignition risk on current trend.",
             "OK to proceed / resume driving.",
             f"cooling {abs(monitor.rise_rate_c_per_s) * 60:0.1f} C/min"],
            (80, 200, 80),  # green (BGR)
        )
    elif phase is Phase.MONITORING:
        eta = monitor.eta_to_ait_s
        if eta is not None and monitor.rise_rate_c_per_s >= MIN_RISE_RATE_C_PER_S:
            note = f"Rising, est. ignition in ~{eta / 60:0.0f} min (beyond {HORIZON_S / 60:0.0f} min)"
        else:
            note = "Temperature steady - monitoring"
        _overlay_box(frame, ["MONITORING", note], (40, 200, 255), anchor="top")
