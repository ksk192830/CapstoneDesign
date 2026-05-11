from dataclasses import dataclass


@dataclass
class ControlCommand:
    seq: int
    motor_left: int
    motor_right: int
    servo_angle: int

