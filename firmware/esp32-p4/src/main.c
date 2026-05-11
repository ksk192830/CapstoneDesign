#include "camera_capture.h"
#include "http_camera_server.h"
#include "wifi_station.h"

#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "app_main";

void app_main(void)
{
    ESP_LOGI(TAG, "ESP32-P4 camera firmware starting");

    esp_err_t ret = camera_capture_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Camera init failed: %s", esp_err_to_name(ret));
        return;
    }

    ret = wifi_station_connect();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi connect failed: %s", esp_err_to_name(ret));
        return;
    }

    ret = http_camera_server_start();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "HTTP server failed: %s", esp_err_to_name(ret));
        return;
    }

    ESP_LOGI(TAG, "Ready. Open http://<device-ip>/capture/visible.raw from the laptop.");

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
