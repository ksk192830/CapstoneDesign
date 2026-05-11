#include "camera_capture.h"
#include "http_camera_server.h"
#include "wifi_station.h"

#include <stdio.h>

#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "app_main";

static void stay_alive(void)
{
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1000));
    printf("\n[BOOT] ESP32-P4 camera firmware starting\n");
    ESP_LOGI(TAG, "ESP32-P4 camera firmware starting");

    esp_err_t ret = wifi_station_connect();
    if (ret != ESP_OK) {
        printf("[ERROR] Wi-Fi connect failed: %s\n", esp_err_to_name(ret));
        ESP_LOGE(TAG, "Wi-Fi connect failed: %s", esp_err_to_name(ret));
        stay_alive();
    }

    printf("[OK] Wi-Fi connected. Initializing camera...\n");

    ret = camera_capture_init();
    if (ret != ESP_OK) {
        printf("[ERROR] Camera init failed: %s\n", esp_err_to_name(ret));
        ESP_LOGE(TAG, "Camera init failed: %s", esp_err_to_name(ret));
        stay_alive();
    }

    ret = http_camera_server_start();
    if (ret != ESP_OK) {
        printf("[ERROR] HTTP server failed: %s\n", esp_err_to_name(ret));
        ESP_LOGE(TAG, "HTTP server failed: %s", esp_err_to_name(ret));
        stay_alive();
    }

    printf("[READY] Open http://<device-ip>/capture/visible.raw from the laptop.\n");
    ESP_LOGI(TAG, "Ready. Open http://<device-ip>/capture/visible.raw from the laptop.");

    stay_alive();
}
