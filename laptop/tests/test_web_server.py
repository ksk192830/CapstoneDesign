from machine_vision_client.ui.web_server import FrameBus, HeatWebServer


class _StubPipeline:
    def __init__(self):
        self.density = 4
        self.min_conf = 20.0

    def adjust_density(self, delta):
        self.density += delta
        return self.density

    def adjust_min_conf(self, delta):
        self.min_conf += delta
        return self.min_conf


def _client():
    bus = FrameBus()
    pipeline = _StubPipeline()
    server = HeatWebServer(bus, pipeline, "127.0.0.1", 8000)
    return server.app.test_client(), bus, pipeline


def test_frame_bus_publish_then_stream_yields_latest():
    bus = FrameBus()
    bus.publish("rgb", b"JPEGDATA")
    part = next(bus.stream("rgb"))
    assert part.startswith(b"--frame")
    assert b"JPEGDATA" in part


def test_index_serves_page_with_feeds():
    client, _bus, _pipe = _client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"rgb.mjpg" in resp.data
    assert b"thermal.mjpg" in resp.data


def test_control_density_adjusts_pipeline():
    client, _bus, pipe = _client()
    resp = client.post("/control/density?delta=1")
    assert resp.status_code == 200
    assert resp.get_json()["density"] == 5
    assert pipe.density == 5


def test_control_min_conf_adjusts_pipeline():
    client, _bus, pipe = _client()
    resp = client.post("/control/min_conf?delta=-5")
    assert resp.status_code == 200
    assert resp.get_json()["min_conf"] == 15.0
    assert pipe.min_conf == 15.0
