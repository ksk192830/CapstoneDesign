#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "thermal_config.h"

typedef struct {
    uint32_t ts_ms;                    /* board uptime in ms at frame end */
    float    temps_c[MLX_PIXELS];      /* 768 floats, row-major (24x32) */
} thermal_frame_t;

/* Spawns the FreeRTOS reader task that keeps an internal frame buffer
 * up to date. Call once after Wi-Fi is up. */
esp_err_t thermal_task_start(void);

/* Copy the most recent complete frame into *out.
 * Returns ESP_OK on success, ESP_ERR_NOT_FOUND if no frame is ready yet,
 * ESP_ERR_TIMEOUT if the lock is held too long, or ESP_ERR_INVALID_ARG. */
esp_err_t thermal_task_get_latest(thermal_frame_t *out);
