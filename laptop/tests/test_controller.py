from machine_vision_client.control import controller


def test_controller_exports_motor_stack():
    assert hasattr(controller, "MotorHttpClient")
    assert hasattr(controller, "DriveVector")


def test_controller_no_longer_exports_opencv_panel():
    assert not hasattr(controller, "DrivePanel")
    assert not hasattr(controller, "CAR_WIN")
