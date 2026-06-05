import threading

from machine_vision_client.ui.web_server import FrameBus, HeatWebServer


class _StubRisk:
    score = 7
    last_event = "test event"


class _StubPipeline:
    def __init__(self):
        self.density = 4
        self.min_conf = 20.0
        self.risk = _StubRisk()
        self.risk_lock = threading.Lock()

    def adjust_density(self, delta):
        self.density += delta
        return self.density

    def adjust_min_conf(self, delta):
        self.min_conf += delta
        return self.min_conf


class _FakeMotor:
    def __init__(self):
        self.calls = []
        self.last_error = None
        self.last_status = {"state": "ok"}

    def set_vector(self, x, y, r):
        self.calls.append((x, y, r))


def _client():
    bus = FrameBus()
    pipeline = _StubPipeline()
    motor = _FakeMotor()
    server = HeatWebServer(bus, pipeline, "127.0.0.1", 8000, motor=motor)
    return server.app.test_client(), bus, pipeline, motor


def test_frame_bus_publish_then_stream_yields_latest():
    bus = FrameBus()
    bus.publish("rgb", b"JPEGDATA")
    part = next(bus.stream("rgb"))
    assert part.startswith(b"--frame")
    assert b"JPEGDATA" in part


def test_index_serves_page_with_feeds():
    client, _bus, _pipe, _motor = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"rgb.mjpg" in resp.data
    assert b"thermal.mjpg" in resp.data


def test_control_density_adjusts_pipeline():
    client, _bus, pipe, _motor = _client()
    resp = client.post("/control/density?delta=1")
    assert resp.status_code == 200
    assert resp.get_json()["density"] == 5
    assert pipe.density == 5


def test_control_min_conf_adjusts_pipeline():
    client, _bus, pipe, _motor = _client()
    resp = client.post("/control/min_conf?delta=-5")
    assert resp.status_code == 200
    assert resp.get_json()["min_conf"] == 15.0
    assert pipe.min_conf == 15.0


def test_control_drive_sets_motor_vector():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/drive", json={"x": 0.5, "y": -1.0, "r": 0.25})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert motor.calls == [(0.5, -1.0, 0.25)]


def test_control_drive_defaults_missing_axes_to_zero():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/drive", json={"y": 1.0})
    assert resp.status_code == 200
    assert motor.calls == [(0.0, 1.0, 0.0)]


def test_control_drive_without_motor_is_noop():
    # The server can run without a motor; the route must still 200.
    bus = FrameBus()
    server = HeatWebServer(bus, _StubPipeline(), "127.0.0.1", 8000)  # motor=None
    resp = server.app.test_client().post("/control/drive", json={"x": 1.0})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_control_drive_rejects_non_numeric_vector():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/drive", json={"x": "fast"})
    assert resp.status_code == 400
    assert motor.calls == []


def test_control_stop_zeroes_motor_vector():
    client, _bus, _pipe, motor = _client()
    resp = client.post("/control/stop")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert motor.calls == [(0.0, 0.0, 0.0)]
