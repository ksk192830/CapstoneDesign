"""Resilience tests for the RGB source wrapper.

A network camera (ESP32 MJPEG) can drop out at any time. `VisibleStream.read`
must degrade to returning None — never raise — so the main loop can wait and
reconnect instead of crashing.
"""

from machine_vision_client.video.visible_stream import VisibleStream


class _RaisingCap:
    """A capture whose .read() blows up, like cv2 on a dropped stream."""

    def isOpened(self):
        return True

    def read(self):
        raise OSError("stream dropped")

    def release(self):
        pass


def test_read_returns_none_when_capture_read_raises():
    vs = VisibleStream(source="http://10.0.0.1:81/stream.mjpg")
    vs._cap = _RaisingCap()
    assert vs.read() is None  # must not propagate the OSError


def test_read_returns_none_when_source_cannot_open(monkeypatch):
    # When (re)opening the source raises (board offline), read must swallow it
    # and return None so the main loop keeps retrying instead of crashing.
    import machine_vision_client.video.visible_stream as vsmod

    def _boom(_source):
        raise RuntimeError("Cannot open RGB source")

    monkeypatch.setattr(vsmod, "open_rgb_capture", _boom)
    vs = VisibleStream(source="http://10.0.0.1:81/stream.mjpg")
    assert vs.read() is None  # _cap is None -> open() raises -> swallowed
