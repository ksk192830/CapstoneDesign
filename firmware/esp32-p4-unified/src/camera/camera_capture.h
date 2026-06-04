#pragma once

#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>

typedef struct {
    const uint8_t *data;
    size_t length;
    uint32_t index;
} camera_frame_t;

esp_err_t camera_capture_init(void);
esp_err_t camera_capture_grab_once(void);
esp_err_t camera_capture_get_frame(camera_frame_t *frame);
esp_err_t camera_capture_release_frame(const camera_frame_t *frame);
