# Protocol

The first version of the protocol uses JSON messages.

Required common fields:

- `type`: Message type.
- `seq`: Monotonic sequence number.
- `timestamp`: Sender timestamp when available.

Example control command:

```json
{
  "type": "control",
  "seq": 1,
  "timestamp": 0.0,
  "mode": "manual",
  "command": {
    "motor_left": 0,
    "motor_right": 0,
    "servo_angle": 90
  }
}
```

