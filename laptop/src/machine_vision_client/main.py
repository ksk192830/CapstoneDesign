"""Heat algorithm web app: RGB + thermal -> material -> risk, served in a browser.

Reads the RGB and thermal cameras, runs material classification + fire-risk
scoring on a background thread, draws the overlay/HUD, and publishes two MJPEG
feeds (RGB+overlay, cropped thermal) over HTTP. Open WEB_HOST:WEB_PORT in a
browser. Stop with Ctrl-C.
"""

from __future__ import annotations

import time

import cv2

from machine_vision_client.config import (
    LOCAL_DEV,
    MOTOR_BASE_URL,
    RGB_H,
    RGB_SOURCE,
    RGB_W,
    WEB_HOST,
    WEB_PORT,
)
from machine_vision_client.ignition_warning import IgnitionTrendMonitor
from machine_vision_client.materials import load_materials
from machine_vision_client.thermal import detect_hotspot
from machine_vision_client.ui.debug_viewer import (
    DebugViewer,
    draw_ignition_overlay,
    format_status,
)
from machine_vision_client.control.motor_http import MotorHttpClient
from machine_vision_client.ui.web_server import FrameBus, HeatWebServer
from machine_vision_client.video.thermal_stream import ThermalStream
from machine_vision_client.video.visible_stream import VisibleStream, make_error_frame
from machine_vision_client.vision.pipeline import (
    HOTSPOT_THRESHOLD_C,
    PREDICT_EVERY_N_FRAMES,
    VisionPipeline,
)

_TARGET_PERIOD_S = 0.04   # cap the loop at ~25 Hz so a fast/mock source doesn't spin


def _jpeg(image) -> bytes:
    ok, buf = cv2.imencode(".jpg", image)
    return buf.tobytes() if ok else b""


def main() -> None:
    if LOCAL_DEV:
        print("[config] LOCAL_DEV: webcam index 0 + mock thermal")

    materials = load_materials()
    print(f"Loaded {len(materials)} materials from xlsx.")

    thermal = ThermalStream()
    pipeline = VisionPipeline(materials, thermal.proj_kwargs())
    viewer = DebugViewer(materials)
    bus = FrameBus()

    motor = MotorHttpClient(MOTOR_BASE_URL)
    motor.start()
    server = HeatWebServer(bus, pipeline, WEB_HOST, WEB_PORT, motor=motor)
    server.start()
    print(f"[control] motor commands -> {MOTOR_BASE_URL}")
    shown_host = "localhost" if WEB_HOST in ("0.0.0.0", "") else WEB_HOST
    print(f"[web] heat feeds at http://{shown_host}:{WEB_PORT}  (Ctrl-C to stop)")

    visible = VisibleStream()
    print(f"Opening RGB source: {RGB_SOURCE!r}")

    # Trend-based ignition-risk early warning. Owns its own state machine +
    # timing; updated once per frame off the live hotspot, never blocks.
    ignition_monitor = IgnitionTrendMonitor()

    last_result = None
    current_mat = None
    frame_count = 0
    prev_time = time.time()
    fps = 0.0
    consecutive_failures = 0
    is_network_source = isinstance(RGB_SOURCE, str)

    try:
        while True:
            loop_start = time.time()
            frame = visible.read()
            if frame is None:
                consecutive_failures += 1
                # A network source (ESP32 over WiFi) can drop and come back —
                # keep waiting and reconnecting indefinitely rather than exiting.
                if is_network_source:
                    bus.publish("rgb", _jpeg(make_error_frame(RGB_W, RGB_H, "Waiting for stream...")))
                    if consecutive_failures % 10 == 0:
                        print(f"[rgb] stream stalled ({consecutive_failures}x); reopening {RGB_SOURCE!r}")
                        try:
                            visible.reopen()
                        except RuntimeError as e:
                            print(f"[rgb] reopen failed: {e}")
                    time.sleep(0.2)
                    continue
                print("Failed to receive frame.")
                break
            consecutive_failures = 0
            frame_count += 1

            now = time.time()
            dt = now - prev_time
            if dt > 0:
                fps = 1.0 / dt
            prev_time = now

            tframe = thermal.read()
            live_hotspot = detect_hotspot(tframe, threshold_c=HOTSPOT_THRESHOLD_C)

            # Sample the live hotspot every frame so the trend window fills
            # without blocking. `current_mat` is the most recently identified
            # material from the (async) inference worker.
            ignition_monitor.update(live_hotspot, current_mat, now)

            if frame_count % PREDICT_EVERY_N_FRAMES == 0:
                pipeline.submit(frame, tframe)

            result = pipeline.try_take_result()
            if result is not None:
                last_result = result
                current_mat = result.mat
                with pipeline.risk_lock:
                    cols, rows = pipeline.grid
                    print(format_status(fps, result.hotspot, result.label, result.conf,
                                        result.mat, pipeline.risk, cols, rows)
                          + "  " + ignition_monitor.status_line())

            with pipeline.risk_lock:
                rgb_annotated = viewer.annotate_rgb(frame, last_result, pipeline.risk, fps)
            # Ignition-risk popup/overlay drawn on top of the HUD (UI layer).
            draw_ignition_overlay(rgb_annotated, ignition_monitor, now)
            bus.publish("rgb", _jpeg(rgb_annotated))
            bus.publish("thermal", _jpeg(viewer.render_thermal(tframe, live_hotspot)))

            elapsed = time.time() - loop_start
            if elapsed < _TARGET_PERIOD_S:
                time.sleep(_TARGET_PERIOD_S - elapsed)
    except KeyboardInterrupt:
        print("\n[web] shutting down.")
    finally:
        motor.stop()
        pipeline.stop()
        visible.release()


if __name__ == "__main__":
    main()
