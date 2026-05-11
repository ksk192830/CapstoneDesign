#pragma once

#include "esp_err.h"

esp_err_t camera_capture_init(void);
esp_err_t camera_capture_grab_once(void);

