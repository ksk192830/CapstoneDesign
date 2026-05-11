# Architecture

This project is split into three main parts:

- `firmware/esp32-p4`: ESP32-P4 firmware managed by PlatformIO.
- `laptop`: Laptop-side vision, control, and communication software.
- `shared`: Protocol definitions and examples shared by both sides.

Initial communication plan:

- Video: ESP32 to laptop over HTTP MJPEG or a later low-latency stream.
- Control: Laptop to ESP32 over WebSocket JSON.
- Status: ESP32 to laptop over WebSocket JSON.

