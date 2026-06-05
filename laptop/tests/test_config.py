from machine_vision_client import config


def test_motor_base_url_derives_from_motor_host():
    assert config.MOTOR_BASE_URL == f"http://{config.MOTOR_HOST}"
    assert config.MOTOR_BASE_URL.startswith("http://")


def test_motor_host_defaults_to_esp32_host():
    # With no MOTOR_HOST override, motors share the camera board's host
    # (the one-board end state).
    assert config.MOTOR_HOST == config.ESP32_HOST
