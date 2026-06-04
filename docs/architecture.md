# Architecture

This project is split into these main parts:

- `firmware/esp32-p4`: ESP32-P4 firmware from **main** — camera, thermal, **omni-wheel motor control**, variable-port HTTP (see recent `main` commits).
- `firmware/esp32-p4-unified`: ESP32-P4 **unified** firmware from **ethan** — OV5647 + MLX90640 on one board; dual HTTP servers (camera `:80`, thermal `:81`). Used by the heat-algorithm laptop client today.
- `laptop`: Laptop-side vision, control, and communication software (`machine_vision_client` package).
- `shared`: Protocol definitions and examples shared by both sides.
- `docs`: Architecture, hardware, and protocol reference.

## Branch merge note (`merge/main-ethan`)

Both firmware trees are kept side-by-side until unified:

| Tree | Source branch | Laptop client | Notable features |
|---|---|---|---|
| `firmware/esp32-p4` | `main` | `VisibleStream` / future WebSocket control | Motor drive, variable ports |
| `firmware/esp32-p4-unified` | `ethan` | `heat_algorithm.py` (fire-risk pipeline) | Split camera/thermal HTTP, MLX90640 |

Long-term goal: one firmware target + one laptop entry point. Until then, flash the tree that matches what you're testing.

## Communication plan

- Video: ESP32 → laptop over HTTP MJPEG or single-frame JPEG.
- Control: Laptop → ESP32 over WebSocket JSON (stub in `laptop/src/machine_vision_client/comms/`).
- Status: ESP32 → laptop over WebSocket JSON.

## HTTP endpoints

Visible camera:

```text
GET /capture/visible.jpg
GET /stream.mjpg          # esp32-p4-unified (actual path in firmware)
GET /stream/visible.mjpeg # protocol doc name; may differ by firmware tree
```

Thermal:

```text
GET /thermal/frame        # port 81 on esp32-p4-unified
```

See `docs/protocol.md` for the full WebSocket envelope and control messages.
