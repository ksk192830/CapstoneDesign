#pragma once

#include <stddef.h>

#include "esp_err.h"

esp_err_t wifi_station_connect(void);

const char *wifi_station_get_ip_string(void);
