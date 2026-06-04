# Hardware

Target board:

- Waveshare ESP32-P4-Module
- Wi-Fi: 802.11 b/g/n/ax
- Flash: 16 MB
- PSRAM: 32 MB
- Main MCU: ESP32-P4
- Wi-Fi coprocessor: ESP32-C6

Record hardware details here as the design becomes fixed:

- Camera module model and interface.
- Infrared or thermal camera model and interface.
- Wi-Fi module connection.
- Power supply requirements.
- Motor, servo, relay, or actuator pin map.

## Current Camera Direction

Candidate camera:

- OV5647 camera module
- Expected interface: MIPI CSI

Implementation direction:

- Use ESP-IDF camera controller APIs for ESP32-P4.
- Do not use the classic `esp32-camera` Arduino driver path for this camera.
- Start with single-frame capture before adding Wi-Fi streaming.

Firmware setup:

- PlatformIO framework: `espidf`
- Camera stack: `espressif/esp_video` + `espressif/esp_cam_sensor`
- Initial video device: `/dev/video0`
- Board control pin config: `firmware/esp32-p4/src/camera/camera_board_config.h`

Open hardware checks:

- Confirm the exact camera module connector pinout.
- Confirm the ESP32-P4 board or carrier board exposes a compatible MIPI CSI connector.
- Confirm whether the module is a bare castellated module or mounted on a carrier board.
