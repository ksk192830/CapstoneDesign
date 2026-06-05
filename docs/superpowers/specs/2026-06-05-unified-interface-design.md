# Unified Interface Design — one web UI, one board

**Date:** 2026-06-05
**Status:** Approved (design)
**Branch:** `merge/main-ethan`

## Goal

Merge the heat-algorithm vision pipeline and the car drive control into a
**single browser interface**: two camera feeds (RGB + thermal) on top, drive
controls on the bottom. End state is **one ESP32-P4 firmware/board** serving
camera, thermal, and motor control, driven by **one laptop process** and **one
web page**.

## Decisions (locked)

| Question | Decision |
|---|---|
| Unified interface | Web browser UI (extend the existing Flask MJPEG server) |
| Hardware target | One unified ESP32-P4 firmware/board |
| Control transport | HTTP `/control/manual` (reuse `MotorHttpClient`) |
| Drive input | Keyboard (WASD + Q/E) **and** on-screen joystick/buttons |
| OpenCV `DrivePanel` | Deleted — the web UI fully replaces it |
| `MOTOR_HOST` default | `ESP32_HOST` (assumes the one-board end state) |

## The seam: the HTTP contract

All components communicate over a fixed HTTP contract on one host. This contract
does not change between sub-projects, which is what lets the laptop UI ship
before the firmware merge.

- `GET  /stream.mjpg` — camera (RGB), MJPEG (firmware `:80`)
- `GET  :81/thermal/frame` — thermal frame
- `GET  /control/manual?x&y&r&ttl` — set omni-drive vector (TTL deadman)
- `GET  /control/stop` — stop motors
- `GET  /control/status` — motor/board status JSON

## Decomposition

Two sub-projects joined by the HTTP contract, built in order.

### Sub-project A — Unified laptop web UI (build first)

The user-visible "merge". Testable today against the existing two boards
(camera+thermal on `esp32-p4-unified`, motors on `esp32-p4`) via config, with no
firmware changes required.

### Sub-project B — Unified firmware (build second)

Collapse both firmware trees onto one ESP32-P4 so a single board satisfies the
whole contract. Laptop change is config-only (`MOTOR_HOST = ESP32_HOST`).

---

## Sub-project A — detailed design

### Architecture (single process, existing shape)

```
main.py (main thread)              background threads
─────────────────────             ─────────────────────
heat loop ──publish──► FrameBus ──► HeatWebServer (Flask daemon)
                                       ├── GET  /rgb.mjpg, /thermal.mjpg
                                       ├── POST /control/drive {x,y,r} ─► MotorHttpClient.set_vector()
                                       ├── POST /control/stop          ─► MotorHttpClient.set_vector(0,0,0)
                                       └── GET  /status (risk + motor health)
                                   MotorHttpClient (own daemon thread)
                                       └── polls ESP32 /control/manual|stop|status, TTL deadman
```

No new processes or threads beyond what exists today. The change is: additional
Flask routes, one `MotorHttpClient` instance, and a redesigned page.

### Components

**`ui/web_server.py` (modified)**
- `HeatWebServer.__init__` gains a `motor: MotorHttpClient` parameter.
- New routes:
  - `POST /control/drive` — JSON body `{x, y, r}`, floats in [-1, 1] → `motor.set_vector(x, y, r)`; returns `{ok: true}`.
  - `POST /control/stop` → `motor.set_vector(0, 0, 0)`; returns `{ok: true}`.
  - `GET /status` → JSON `{risk: <score>, event: <str>, motor_ok: <bool>, motor_error: <str|null>, motor_status: <last_status|null>}`.
- Existing feed + tuning routes unchanged.
- The inline `_PAGE` string is extracted to a template file (it is outgrowing a
  string literal once control UI + JS are added).

**`ui/templates/index.html` (new)**
- Top: two `<img>` MJPEG feeds (`/rgb.mjpg`, `/thermal.mjpg`) side by side.
- Bottom: drive control panel — on-screen joystick/D-pad + STOP button, a live
  status line, and the existing grid/min-conf tuning buttons.
- JS:
  - Keyboard: WASD = translate (x/y), Q/E = rotate (r); track pressed keys,
    recompute the vector on keydown/keyup.
  - On-screen joystick/D-pad: pointer events → normalized `{x, y}`; rotate
    buttons → `r`.
  - Throttled `POST /control/drive` at ~15 Hz while the vector is non-zero.
  - Zero-vector (stop) on `keyup` to neutral, window `blur`, and `touchend`.
  - Spacebar and the STOP button send an immediate zero vector.
  - Poll `GET /status` ~2 Hz to update the risk badge + motor health badge.

**`main.py` (modified)**
- Build `MotorHttpClient(MOTOR_BASE_URL)`, `start()` it, pass to `HeatWebServer`.
- `motor.stop()` in the `finally` block alongside `pipeline.stop()`.

**`config.py` (modified)**
- `MOTOR_HOST = os.environ.get("MOTOR_HOST", ESP32_HOST)`
- `MOTOR_BASE_URL = f"http://{MOTOR_HOST}"`
- In `LOCAL_DEV`, motor control is effectively a no-op target (errors surface in
  `/status` but do not affect the vision feeds).

**Removed**
- `control/drive_panel.py` (OpenCV `DrivePanel`, `CAR_WIN`) and any references.
- `motor_http.py` is **kept** and reused unchanged.

### Data flow (drive command)

1. Browser computes `{x, y, r}` from keyboard/joystick state.
2. Throttled `POST /control/drive` (~15 Hz) → `motor.set_vector(x, y, r)`
   (thread-safe setpoint).
3. `MotorHttpClient`'s loop sends `/control/manual?...&ttl=300` while the vector
   is non-zero; sends `/control/stop` once when it returns to zero.

### Error handling & safety

- **Two independent deadman stops:** (1) JS sends a zero vector on keyup / window
  blur / touchend; (2) firmware auto-stops if no command arrives within
  `ttl_ms` (300 ms).
- **Motor unreachable:** `MotorHttpClient.last_error` surfaces in `/status`; the
  page shows a red "motor offline" badge. **Camera feeds keep running** — vision
  and control degrade independently.
- **Explicit STOP:** spacebar + on-screen STOP button → immediate zero vector.

### Testing

`tests/test_web_server.py` (extended), using a fake/recording motor object:
- `POST /control/drive` with `{x,y,r}` calls `motor.set_vector` with those values.
- `POST /control/stop` calls `set_vector(0, 0, 0)`.
- `GET /status` returns the expected JSON shape (risk + motor fields).
- `GET /` renders the page (200, contains both feed `<img>` tags and the control
  panel).

A fake motor (records `set_vector` calls) keeps tests free of real HTTP/hardware.

---

## Sub-project B — unified firmware (high-level follow-on)

Merge the motor `/control/*` endpoints and motor-driver code from
`firmware/esp32-p4` into `firmware/esp32-p4-unified`, so a single ESP32-P4 image
serves camera MJPEG (`:80`), thermal (`:81`), and motor control. Work items:

- Reconcile pin/peripheral allocation (camera + thermal I2C + motor PWM/outputs).
- Single WiFi station + the existing dual HTTP servers, adding the `/control/*`
  handlers.
- Verify power/timing under simultaneous camera streaming + motor drive.
- Laptop change: set `MOTOR_HOST = ESP32_HOST` (one IP). No UI rework.

This sub-project gets its own spec + plan once A is complete.

## Out of scope

- WebSocket JSON control (the `shared/protocol/` v1 schema + `comms/` stubs) —
  HTTP `/control/manual` is the chosen transport for now.
- Autonomous driving / closing the loop between risk score and drive commands.
- Consolidating the two `.xlsx` copies (tracked separately).
