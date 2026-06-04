"""Tests for HttpThermalSource — polls /thermal/frame, hands ThermalFrame to consumers."""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "machine_vision_client"))

from thermal import HttpThermalSource, THERMAL_W, THERMAL_H  # noqa: E402


class _FakeEsp(BaseHTTPRequestHandler):
    """Fixture: returns whatever JSON `self.server.payload` currently holds."""

    def log_message(self, *args, **kwargs):
        pass

    def do_GET(self):
        if self.path != "/thermal/frame":
            self.send_error(404)
            return
        body = self.server.payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeEsp)
    srv.payload = '{"event":"warming_up"}'
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()


def _good_frame_payload() -> str:
    temps = [20.0 + (i % 100) * 0.1 for i in range(THERMAL_W * THERMAL_H)]
    return json.dumps({"ts": 12345, "temps_c": temps})


def test_read_returns_ambient_until_first_frame_arrives(fake_server):
    url = f"http://127.0.0.1:{fake_server.server_address[1]}/thermal/frame"
    src = HttpThermalSource(url, poll_hz=20)
    try:
        time.sleep(0.1)
        frame = src.read()
        assert frame.temps_c.shape == (THERMAL_H, THERMAL_W)
        assert np.allclose(frame.temps_c, 24.0)
    finally:
        src.close()


def test_read_returns_parsed_frame_once_payload_is_good(fake_server):
    fake_server.payload = _good_frame_payload()
    url = f"http://127.0.0.1:{fake_server.server_address[1]}/thermal/frame"
    src = HttpThermalSource(url, poll_hz=20)
    try:
        f = None
        deadline = time.time() + 1.0
        while time.time() < deadline:
            f = src.read()
            if not np.allclose(f.temps_c, 24.0):
                break
            time.sleep(0.02)
        assert f is not None
        assert f.temps_c.shape == (THERMAL_H, THERMAL_W)
        assert f.temps_c.dtype == np.float32
        assert abs(float(f.temps_c[0, 0]) - 20.0) < 1e-3
        # Index 767 → (767 % 100) * 0.1 = 6.7 → 26.7
        assert abs(float(f.temps_c[-1, -1]) - 26.7) < 1e-3
    finally:
        src.close()


def test_read_survives_server_outage(fake_server):
    fake_server.payload = _good_frame_payload()
    url = f"http://127.0.0.1:{fake_server.server_address[1]}/thermal/frame"
    src = HttpThermalSource(url, poll_hz=20)
    try:
        time.sleep(0.2)
        first = src.read()
        assert first.temps_c.max() > 24.5

        fake_server.shutdown()
        time.sleep(0.1)
        f = src.read()
        assert f.temps_c.shape == (THERMAL_H, THERMAL_W)
    finally:
        src.close()
