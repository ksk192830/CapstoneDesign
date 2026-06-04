#pragma once

#include "driver/gpio.h"

// Board-specific control pins for the MIPI-CSI camera connector.
//
// These are not the high-speed CSI data lanes. They are low-speed control pins
// used for SCCB/I2C sensor configuration and optional reset/power-down control.
// Confirm these values from the exact ESP32-P4 carrier board schematic.

#define CAMERA_SCCB_I2C_PORT 0
#define CAMERA_SCCB_SDA_PIN GPIO_NUM_7
#define CAMERA_SCCB_SCL_PIN GPIO_NUM_8
#define CAMERA_RESET_PIN GPIO_NUM_NC
#define CAMERA_PWDN_PIN GPIO_NUM_NC

#define CAMERA_SCCB_FREQ_HZ 100000
#define CAMERA_VIDEO_DEVICE "/dev/video0"

