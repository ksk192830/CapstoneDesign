"""Browser web interface for the heat algorithm (Flask + MJPEG).

`FrameBus` is a thread-safe latest-frame holder: the capture/inference loop
publishes annotated JPEG frames, and per-client MJPEG generators stream the most
recent one. `HeatWebServer` serves a page with two `<img>` feeds (RGB+overlay and
cropped thermal) plus live-tuning controls, running in a daemon thread so it
never blocks the model loop.
"""

from __future__ import annotations

import threading

from flask import Flask, Response, jsonify, render_template, request

_BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"


class FrameBus:
    """Thread-safe holder of the latest published JPEG frame per channel."""

    def __init__(self):
        self._cond = threading.Condition()
        self._frames: dict[str, bytes | None] = {"rgb": None, "thermal": None}
        self._seq: dict[str, int] = {"rgb": 0, "thermal": 0}

    def publish(self, which: str, jpeg: bytes) -> None:
        with self._cond:
            self._frames[which] = jpeg
            self._seq[which] += 1
            self._cond.notify_all()

    def stream(self, which: str):
        """Yield multipart MJPEG parts: a new frame when available, else a
        keepalive re-send of the latest every couple of seconds."""
        last = -1
        while True:
            with self._cond:
                if self._seq[which] == last:
                    self._cond.wait(timeout=2.0)
                jpeg = self._frames[which]
                last = self._seq[which]
            if jpeg is not None:
                yield _BOUNDARY + jpeg + b"\r\n"


class HeatWebServer:
    """Flask app streaming the two heat feeds + live-tuning control endpoints."""

    def __init__(self, bus: FrameBus, pipeline, host: str, port: int, motor=None):
        self._bus = bus
        self._pipeline = pipeline
        self._host = host
        self._port = port
        self._motor = motor
        self._app = Flask(__name__)
        self._register_routes()

    @property
    def app(self) -> Flask:
        return self._app

    def _register_routes(self) -> None:
        app = self._app

        @app.route("/")
        def index():
            return render_template("index.html")

        @app.route("/rgb.mjpg")
        def rgb():
            return Response(self._bus.stream("rgb"),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/thermal.mjpg")
        def thermal():
            return Response(self._bus.stream("thermal"),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/control/density", methods=["POST"])
        def density():
            delta = int(request.args.get("delta", "0"))
            return jsonify(density=self._pipeline.adjust_density(delta))

        @app.route("/control/min_conf", methods=["POST"])
        def min_conf():
            delta = float(request.args.get("delta", "0"))
            return jsonify(min_conf=self._pipeline.adjust_min_conf(delta))

        @app.route("/control/drive", methods=["POST"])
        def drive():
            data = request.get_json(silent=True) or {}
            try:
                x = float(data.get("x", 0.0))
                y = float(data.get("y", 0.0))
                r = float(data.get("r", 0.0))
            except (TypeError, ValueError):
                return jsonify(error="invalid drive vector"), 400
            if self._motor is not None:
                self._motor.set_vector(x, y, r)
            return jsonify(ok=True)

        @app.route("/control/stop", methods=["POST"])
        def stop():
            if self._motor is not None:
                self._motor.set_vector(0.0, 0.0, 0.0)
            return jsonify(ok=True)

        @app.route("/status")
        def status():
            with self._pipeline.risk_lock:
                score = self._pipeline.risk.score
                event = self._pipeline.risk.last_event
            motor = self._motor
            return jsonify(
                risk=score,
                event=event,
                motor_ok=(motor is not None and motor.last_error is None),
                motor_error=(motor.last_error if motor is not None else "no motor"),
                motor_status=(motor.last_status if motor is not None else None),
            )

    def start(self) -> threading.Thread:
        thread = threading.Thread(
            target=lambda: self._app.run(
                host=self._host, port=self._port, threaded=True,
                debug=False, use_reloader=False,
            ),
            daemon=True,
        )
        thread.start()
        return thread
