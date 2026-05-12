#include "camera_capture.h"
#include "http_camera_server.h"
#include "wifi_station.h"

#include <stdio.h>

#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"


static void stay_alive(void)
{
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_log_level_set("*", ESP_LOG_WARN);
    printf("\n[BOOT] ESP32-P4 camera firmware starting\n");

    esp_err_t ret = wifi_station_connect();
    if (ret != ESP_OK) {
        printf("[ERROR] Wi-Fi connect failed: %s\n", esp_err_to_name(ret));
        stay_alive();
    }

    printf("[WIFI] connected\n");

    ret = camera_capture_init();
    if (ret != ESP_OK) {
        printf("[ERROR] Camera init failed: %s\n", esp_err_to_name(ret));
        stay_alive();
    }

    ret = http_camera_server_start();
    if (ret != ESP_OK) {
        printf("[ERROR] HTTP server failed: %s\n", esp_err_to_name(ret));
        stay_alive();
    }

    const char *ip = wifi_station_get_ip_string();
    printf("[READY] open: http://%s/\n", ip);
    printf("[READY] stream: http://%s/stream.mjpg\n", ip);

    stay_alive();
}
