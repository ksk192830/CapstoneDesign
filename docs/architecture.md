# Architecture

This project is split into three main parts:

- `firmware/esp32-p4-unified`: ESP32-P4 unified firmware (OV5647 + MLX90640) managed by PlatformIO.
- `laptop`: Laptop-side vision, control, and communication software (`machine_vision_client` package).
- `shared`: Protocol definitions and examples shared by both sides.
- `docs`: Architecture, hardware, and protocol reference.

Initial communication plan:

- Video: ESP32 to laptop over HTTP MJPEG or a later low-latency stream.
- Control: Laptop to ESP32 over WebSocket JSON.
- Status: ESP32 to laptop over WebSocket JSON.

Initial camera endpoints:

- `GET /`: device status text.
- `GET /capture.jpg`: single JPEG frame.
- `GET /stream/visible.mjpeg`: MJPEG stream for OpenCV/browser viewing.
