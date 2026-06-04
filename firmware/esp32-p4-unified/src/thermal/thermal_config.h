#pragma once

#include "driver/gpio.h"
#include "driver/i2c_master.h"

/* MLX90640 I2C wiring. Camera SCCB owns I2C_NUM_0 on GPIO 7/8, so the
 * thermal sensor uses I2C_NUM_1 on a free pair (default GPIO 4/5).
 * Override here if the user's board breakout differs.
 * ESP32-P4 caps I2C at 400 kHz; we configure the bus at that rate. */
#define MLX_I2C_PORT     I2C_NUM_1
#define MLX_I2C_SDA_PIN  GPIO_NUM_21
#define MLX_I2C_SCL_PIN  GPIO_NUM_22
#define MLX_I2C_ADDR     0x33

/* Sensor refresh rate. Values supported by Melexis API code (0..7):
 *   0=0.5Hz, 1=1, 2=2, 3=4, 4=8, 5=16, 6=32, 7=64.
 * 4 Hz full-frame keeps comfortably within the 400 kHz I2C budget. */
#define MLX_REFRESH_HZ   4

#define MLX_ROWS    24
#define MLX_COLS    32
#define MLX_PIXELS  (MLX_ROWS * MLX_COLS)
