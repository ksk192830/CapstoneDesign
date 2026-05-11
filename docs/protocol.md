# Protocol v1

The first project protocol separates video streaming from control messages.

- Video streams use HTTP endpoints.
- Control, status, heartbeat, and error messages use WebSocket JSON.
- The laptop is the control authority.
- The ESP32-P4 is the camera, actuator, and safety endpoint.

## Network Roles

Recommended initial setup:

- ESP32-P4 connects to the same Wi-Fi network as the laptop.
- ESP32-P4 runs an HTTP server and a WebSocket server.
- Laptop connects to the ESP32-P4 IP address.

Default URLs:

```text
http://<esp32-ip>/
http://<esp32-ip>/capture/visible.jpg
http://<esp32-ip>/stream/visible.mjpeg
http://<esp32-ip>/thermal/frame
ws://<esp32-ip>/ws
```

## Video Endpoints

Visible camera:

```text
GET /capture/visible.jpg
GET /stream/visible.mjpeg
```

Thermal or infrared camera:

```text
GET /capture/thermal.jpg
GET /stream/thermal.mjpeg
GET /thermal/frame
```

Use `/thermal/frame` when the sensor returns temperature data rather than a
normal image. The response should be JSON or binary data, depending on the
sensor selected later.

## WebSocket Messages

All WebSocket messages are JSON objects with this common envelope:

```json
{
  "version": 1,
  "type": "message_type",
  "seq": 1,
  "timestamp_ms": 0,
  "payload": {}
}
```

Common fields:

- `version`: Protocol version. Start with `1`.
- `type`: Message type.
- `seq`: Sender-side monotonic sequence number.
- `timestamp_ms`: Sender timestamp in milliseconds when available.
- `payload`: Message-specific body.

## Message Types

Laptop to ESP32-P4:

- `hello`: Session negotiation.
- `control`: Normal actuator command.
- `stop`: Normal stop command.
- `emergency_stop`: Immediate stop command.
- `set_mode`: Change ESP32-side mode.
- `ping`: Heartbeat request.

ESP32-P4 to laptop:

- `hello_ack`: Session negotiation response.
- `status`: Device status.
- `ack`: Command acknowledgement.
- `error`: Error report.
- `pong`: Heartbeat response.

## Control Command

```json
{
  "version": 1,
  "type": "control",
  "seq": 10,
  "timestamp_ms": 123456,
  "payload": {
    "mode": "manual",
    "ttl_ms": 300,
    "motors": {
      "left": 0,
      "right": 0
    },
    "servos": {
      "camera_pan": 90,
      "camera_tilt": 90
    }
  }
}
```

`ttl_ms` is important. If the ESP32-P4 does not receive a fresh valid control
message before the TTL expires, it must stop actuators or enter a safe state.

## Status Message

```json
{
  "version": 1,
  "type": "status",
  "seq": 20,
  "timestamp_ms": 123500,
  "payload": {
    "state": "ok",
    "mode": "manual",
    "wifi_rssi_dbm": -50,
    "uptime_ms": 5000,
    "last_command_seq": 10,
    "camera": {
      "visible": "streaming",
      "thermal": "not_configured"
    }
  }
}
```

## Safety Rules

- ESP32-P4 must stop actuators when command TTL expires.
- ESP32-P4 must stop actuators when WebSocket disconnects.
- `emergency_stop` always overrides normal control.
- Laptop should send `ping` or `control` at a fixed interval during active mode.
- Laptop should treat missing `status` or `pong` responses as a connection fault.

## Versioning

Keep `version: 1` in every WebSocket message. When the protocol changes in a
breaking way, create `Protocol v2` and keep old examples for comparison.
