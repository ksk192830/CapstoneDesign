#include "camera_capture.h"

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

    while (true) {
        ret = camera_capture_grab_once();
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Frame capture failed: %s", esp_err_to_name(ret));
        }

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

