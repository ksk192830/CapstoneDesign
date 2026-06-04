# Setup

How to get the heat-algorithm running end-to-end on your laptop, and what to redo when the WiFi network changes.

This repo follows the [CapstoneDesign](https://github.com/ksk192830/CapstoneDesign) layout. The heat algorithm lives in the **`laptop/`** Python package; firmware stays in **`firmware/esp32-p4-unified/`**.

## Repository layout

```
firmware/esp32-p4-unified/     ESP32-P4 firmware (camera + thermal)
laptop/                        Cross-platform Python client
  src/machine_vision_client/
    heat_algorithm.py          Main RGB + thermal → material → risk loop
    config.py                  ESP32_HOST, LOCAL_DEV, serial-port defaults
docs/                          Architecture, hardware, protocol
shared/                        WebSocket JSON schema + examples
heat_algorithm                 Root launcher (calls the laptop package)
```

## System overview

Two pieces must be on the **same WiFi LAN**:

- **ESP32-P4 board** — firmware in `firmware/esp32-p4-unified/`. Hosts **two HTTP servers**: port **80** for the camera (`/stream.mjpg`, `/capture/visible.jpg`) and port **81** for the thermal sensor (`/thermal/frame`). Separate ports prevent the long-lived MJPEG handler from starving thermal requests.
- **Laptop** — runs the heat algorithm from `laptop/src/machine_vision_client/`. Pulls both streams, classifies materials, shows two OpenCV windows.

---

## First-time laptop setup

### macOS / Linux

From the repo root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "laptop/[dev]"
```

> Do **not** rely on bare `pip` or `huggingface-cli` from `.venv/bin/` if the venv was created before the folder was renamed — those console scripts may have stale shebangs. Always invoke through `.venv/bin/python -m pip …`.

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "laptop/[dev]"
```

For **firmware flashing only**, a separate PlatformIO venv is recommended (see [Platform-specific setup](#platform-specific-setup) below).

### Configuration

Board IP and dev mode are set in `laptop/src/machine_vision_client/config.py`, or via environment variables:

| Variable | Purpose |
|---|---|
| `ESP32_HOST` | Board IP on the LAN (default `172.20.10.8`) |
| `FIRMWARE_PROFILE` | `esp32-p4` (car + heat, default) or `esp32-p4-unified` (heat only) |
| `CAR_CONTROL` | `1` / `0` — omni-wheel panel (auto-on for `esp32-p4`) |
| `HEAT_LOCAL=1` | Webcam index 0 + mock thermal — no ESP32 needed |
| `THERMAL_PORT` | USB serial override (`COM3`, `/dev/cu.usbmodem3101`, …) |

RGB and thermal URLs are derived automatically from `ESP32_HOST` in `config.py`.

---

## Platform-specific setup

macOS/Linux commands are used below by default. Windows equivalents:

| Task | macOS / Linux | Windows |
|---|---|---|
| **Find USB port** | `ls /dev/cu.usbmodem*` | Device Manager → **Ports (COM & LPT)**, or PowerShell: `[System.IO.Ports.SerialPort]::GetPortNames()` |
| **Flash board** | `pio run -t upload --upload-port /dev/cu.usbmodem3101` | `.\venv_windows\Scripts\pio run -t upload --upload-port COM3` |
| **Serial monitor** | `pio device monitor -p /dev/cu.usbmodem3101 -b 115200` | See [Serial monitor (Windows)](#serial-monitor-windows) |
| **Check local IP** | `ipconfig getifaddr en0` | `ipconfig` → WiFi adapter IPv4 |
| **Run algorithm** | `.venv/bin/python heat_algorithm` | `.\.venv\Scripts\python.exe heat_algorithm` |
| **Rebuild venv** | `rm -rf .venv` | `Remove-Item -Recurse .venv` |

**Windows — two venvs (optional but practical):**

| Folder | Purpose |
|---|---|
| `.venv` | Run heat algorithm (torch, OpenCV, transformers, …) |
| `venv_windows` | Flash/monitor ESP32 firmware (PlatformIO only) |

Create the PlatformIO venv once:

```powershell
python -m venv venv_windows
.\venv_windows\Scripts\python.exe -m pip install platformio
```

### Serial monitor (Windows)

If `pio device monitor` fails, use pyserial from `.venv` (close any app holding the COM port first):

```powershell
.\.venv\Scripts\python.exe -m serial.tools.miniterm COM3 115200
```

Press **RST** on the board. Look for:

```
[WIFI] connected
[READY] stream: http://<esp32-ip>/stream.mjpg
[READY] thermal: http://<esp32-ip>:81/thermal/frame
```

Quit with **Ctrl+]**.

---

## When the WiFi changes

Five steps. The ESP32 only learns about a network when you flash new credentials.

### 1. Edit the credentials

Open `firmware/esp32-p4-unified/src/network/wifi_credentials.h`:

```c
#define WIFI_STA_SSID "YourNetwork"
#define WIFI_STA_PASSWORD "YourPassword"
```

### 2. Flash the board

**macOS** — find the USB port:

```bash
ls /dev/cu.usbmodem*
```

**Windows** — find `COM3`, `COM4`, etc. in Device Manager.

Then from the repo root:

```bash
cd firmware/esp32-p4-unified
pio run -t upload --upload-port /dev/cu.usbmodem3101   # or COM3 on Windows
```

Upload finishes with `[SUCCESS]` and the board resets.

### 3. Find the ESP32's new IP

**macOS / Linux:**

```bash
pio device monitor -p /dev/cu.usbmodem3101 -b 115200
```

Press **RST**. Within ~5 s of joining WiFi:

```
I (4102) esp_netif_handlers: sta ip: 172.20.10.8, mask: 255.255.255.0, gw: 172.20.10.1
```

That `sta ip:` value is the board IP. Ctrl+C to exit.

### 4. Put the laptop on the same WiFi

Verify reachability:

```bash
curl -I --max-time 3 http://<esp32-ip>/stream.mjpg
curl -I --max-time 3 http://<esp32-ip>:81/thermal/frame    # note :81
```

Both should return `HTTP/1.1 200 OK`. On macOS, check your laptop IP with `ipconfig getifaddr en0` and confirm it shares the first three octets with the ESP32.

### 5. Point the laptop client at the new IP

```bash
export ESP32_HOST=172.20.10.8          # macOS / Linux
.venv/bin/python heat_algorithm

# Windows PowerShell:
# $env:ESP32_HOST = "172.20.10.8"
# .\.venv\Scripts\python.exe heat_algorithm
```

Or edit `ESP32_HOST` in `laptop/src/machine_vision_client/config.py`.

**Port reminder:** camera is port **80** (`/stream.mjpg`); thermal is port **81** (`/thermal/frame`). Use `/stream.mjpg` for continuous video, not `/capture/visible.jpg` (single still). HTTP thermal takes precedence over `THERMAL_PORT` USB serial when both are configured.

---

## Running the unified app (car + heat algorithm)

Flash **`firmware/esp32-p4`** (motor control + camera + thermal). Then from the repo root:

```bash
export ESP32_HOST=172.20.10.8
.venv/bin/python heat_algorithm
```

Three OpenCV windows open:

| Window | Purpose |
|---|---|
| **Car Control** | Drag the virtual stick or hold on-screen WASD; Q/E buttons rotate |
| **Fire Risk - RGB** | Material grid, hotspot HUD, risk score |
| **Fire Risk - Thermal** | Live thermal view |

- **Space** in the Car Control window — emergency stop
- **Esc** or **q** in the RGB window — quit the app

Heat-only (no car): flash `firmware/esp32-p4-unified` and run with  
`FIRMWARE_PROFILE=esp32-p4-unified CAR_CONTROL=0 .venv/bin/python heat_algorithm`

---

## Running heat algorithm only

From the repo root:

```bash
.venv/bin/python heat_algorithm
```

With **`FIRMWARE_PROFILE=esp32-p4-unified`**, two OpenCV windows open: **Fire Risk - RGB** and **Fire Risk - Thermal**. Press **`q`** or **Esc** in the RGB window to quit.

First run downloads the HuggingFace model `prithivMLmods/Minc-Materials-23` (~350 MB); later runs use the cache at `~/.cache/huggingface/`.

---

## Tuning the thermal window

The MLX90640 has a wider FOV than the OV5647 and may be mounted rotated. Edit these constants at the top of `laptop/src/machine_vision_client/heat_algorithm.py`:

```python
THERMAL_ROTATE_CCW: int = 1       # 0/1/2/3 → 0°/90°/180°/270° CCW
THERMAL_MIRROR_H: bool = True     # flip left/right after rotation
THERMAL_CROP_H_FRAC: float = 0.6  # keep left 60% of columns
THERMAL_CROP_V_FRAC: float = 0.5  # keep top 50% of rows
```

Re-alignment recipe:

1. Set crop fractions to `1.0` to see the full sensor.
2. Adjust `THERMAL_ROTATE_CCW` until vertical features match between windows.
3. Toggle `THERMAL_MIRROR_H` if left/right is reversed.
4. Set crop fractions to exclude thermal regions outside the RGB FOV. FOV scaling updates automatically for hotspot projection.

---

## Troubleshooting

**`Cannot open RGB source` / `urlopen error timed out`**
- Laptop on wrong WiFi → rejoin the ESP32's SSID.
- Stale IP → redo step 3 and update `ESP32_HOST`.
- DHCP gave the board a new lease → redo step 3.

**`Waiting for stream...` loops in OpenCV**
Same as above; the script tolerates stalls and recovers once the IP is correct.

**`pio device monitor` — port busy or won't open**
Another app holds the port (previous monitor, Arduino IDE, or `heat_algorithm` with USB `THERMAL_PORT`). Close it.

**Upload / pip fails with `No such file or directory`**
Stale venv shebangs. Rebuild:

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/python -m pip install -e "laptop/[dev]"
```

**Model load hangs**
First run only — downloading from HuggingFace.

**Import errors after moving files**
Run `.venv/bin/python -m pip install -e "laptop/[dev]"` once, or use the root `heat_algorithm` launcher (it adds `laptop/src` to the path automatically).

---

## Quick reference

| What | Where |
|---|---|
| WiFi SSID / password | `firmware/esp32-p4-unified/src/network/wifi_credentials.h` |
| ESP32 USB port (Mac) | `ls /dev/cu.usbmodem*` |
| ESP32 USB port (Win) | Device Manager → COM & LPT |
| Flash | `pio run -t upload --upload-port <port>` from `firmware/esp32-p4-unified/` |
| Camera URL | `http://<esp32-ip>/stream.mjpg` (port 80) |
| Thermal URL | `http://<esp32-ip>:81/thermal/frame` (port 81) |
| Board IP config | `laptop/src/machine_vision_client/config.py` or `ESP32_HOST` env |
| Thermal align knobs | `laptop/src/machine_vision_client/heat_algorithm.py` |
| Run | `.venv/bin/python heat_algorithm` |
| Local dev | `HEAT_LOCAL=1 .venv/bin/python heat_algorithm` |
| Tests | `cd laptop && ../.venv/bin/python -m pytest tests/ -q` |
