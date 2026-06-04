"""Browser web interface for the heat algorithm (Flask + MJPEG).

`FrameBus` is a thread-safe latest-frame holder: the capture/inference loop
publishes annotated JPEG frames, and per-client MJPEG generators stream the most
recent one. `HeatWebServer` serves a page with two `<img>` feeds (RGB+overlay and
cropped thermal) plus live-tuning controls, running in a daemon thread so it
never blocks the model loop.
"""

from __future__ import annotations

import threading

from flask import Flask, Response, jsonify, request

_BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Fire Risk - Heat Algorithm</title>
<style>
  body{margin:0;background:#111;color:#ddd;font-family:system-ui,sans-serif}
  h1{font-size:18px;padding:10px 14px;margin:0;background:#000}
  .feeds{display:flex;flex-wrap:wrap;gap:12px;padding:12px}
  .feed{background:#000;border:1px solid #333;border-radius:6px;padding:6px}
  .feed h2{font-size:13px;margin:4px 6px;color:#9af}
  img{display:block;max-width:100%;height:auto;background:#222}
  .controls{padding:0 14px 14px}
  button{background:#223;color:#cde;border:1px solid #456;border-radius:5px;
         padding:6px 12px;margin:3px;cursor:pointer;font-size:14px}
  button:hover{background:#345}
  #status{font-size:12px;color:#8a8;margin-left:8px}
</style></head>
<body>
  <h1>Fire Risk - Heat Algorithm</h1>
  <div class="feeds">
    <div class="feed"><h2>RGB + material / risk overlay</h2>
      <img src="/rgb.mjpg" alt="rgb"></div>
    <div class="feed"><h2>Thermal (cropped)</h2>
      <img src="/thermal.mjpg" alt="thermal"></div>
  </div>
  <div class="controls">
    <button onclick="ctl('density',1)">grid +</button>
    <button onclick="ctl('density',-1)">grid -</button>
    <button onclick="ctl('min_conf',5)">min-conf +</button>
    <button onclick="ctl('min_conf',-5)">min-conf -</button>
    <span id="status"></span>
  </div>
  <script>
    async function ctl(name, delta){
      const r = await fetch(`/control/${name}?delta=${delta}`, {method:'POST'});
      const j = await r.json();
      document.getElementById('status').textContent = JSON.stringify(j);
    }
  </script>
</body></html>"""


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

    def __init__(self, bus: FrameBus, pipeline, host: str, port: int):
        self._bus = bus
        self._pipeline = pipeline
        self._host = host
        self._port = port
        self._app = Flask(__name__)
        self._register_routes()

    @property
    def app(self) -> Flask:
        return self._app

    def _register_routes(self) -> None:
        app = self._app

        @app.route("/")
        def index():
            return Response(_PAGE, mimetype="text/html")

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
