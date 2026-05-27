#include "camera_capture.h"
#include "http_camera_server.h"
#include "motor_control.h"
#include "thermal_task.h"
#include "wifi_station.h"

#include <stdio.h>

#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"


static void stay_alive(void)
{
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

static void reset_c6_before_hosted_start(void)
{
    const gpio_num_t c6_en = CONFIG_ESP_HOSTED_GPIO_SLAVE_RESET_SLAVE;

    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << c6_en,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));

    printf("[C6] forcing reset via GPIO%d\n", c6_en);
    gpio_set_level(c6_en, 0);
    vTaskDelay(pdMS_TO_TICKS(1000));
    gpio_set_level(c6_en, 1);
    printf("[C6] released reset, waiting for slave firmware boot\n");
    vTaskDelay(pdMS_TO_TICKS(5000));
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_log_level_set("*", ESP_LOG_WARN);
    printf("\n[BOOT] ESP32-P4 camera firmware starting\n");

    reset_c6_before_hosted_start();

    esp_err_t ret = wifi_station_connect();
    if (ret != ESP_OK) {
        printf("[ERROR] Wi-Fi connect failed: %s\n", esp_err_to_name(ret));
        stay_alive();
    }

    printf("[WIFI] connected\n");
    const char *ip = wifi_station_get_ip_string();
    printf("[READY] open: http://%s/\n", ip);
    printf("[READY] stream: http://%s:81/stream.mjpg\n", ip);
    printf("[READY] thermal: http://%s/thermal\n", ip);
    printf("[MOTOR] init starts in 3 seconds\n");
    vTaskDelay(pdMS_TO_TICKS(3000));

    ret = motor_control_init();
    if (ret != ESP_OK) {
        printf("[ERROR] Motor control init failed: %s\n", esp_err_to_name(ret));
        stay_alive();
    }
    printf("[MOTOR] manual control ready\n");

    ret = thermal_task_start();
    if (ret != ESP_OK) {
        printf("[WARN] thermal task start failed: %s -- continuing without thermal\n",
               esp_err_to_name(ret));
    } else {
        printf("[THERMAL] reader task running\n");
    }

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

    stay_alive();
}
