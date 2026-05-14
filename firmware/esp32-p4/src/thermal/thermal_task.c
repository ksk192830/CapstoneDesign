#include "thermal_task.h"

#include <string.h>

#include "MLX90640_API.h"
#include "MLX90640_I2C_Driver.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "thermal_task";

/* Internal double buffer: writer fills s_back, then under the mutex
 * swaps it into s_front. Readers (HTTP handler) copy s_front. */
static thermal_frame_t  s_front;
static thermal_frame_t  s_back;
static bool             s_have_frame = false;
static SemaphoreHandle_t s_mutex;

/* MLX90640 EEPROM is 832 16-bit words; frame buffer is 834 words. */
static uint16_t s_eeprom[832];
static uint16_t s_frame_raw[834];
static paramsMLX90640 s_params;

static int rate_code_from_hz(int hz)
{
    switch (hz) {
        case 1:  return 1;
        case 2:  return 2;
        case 4:  return 3;
        case 8:  return 4;
        case 16: return 5;
        case 32: return 6;
        case 64: return 7;
        default: return 3;  /* 4 Hz */
    }
}

static void thermal_reader_task(void *arg)
{
    (void)arg;

    if (MLX90640_DumpEE(MLX_I2C_ADDR, s_eeprom) != 0) {
        ESP_LOGE(TAG, "DumpEE failed");
        vTaskDelete(NULL);
        return;
    }
    if (MLX90640_ExtractParameters(s_eeprom, &s_params) != 0) {
        ESP_LOGE(TAG, "ExtractParameters failed");
        vTaskDelete(NULL);
        return;
    }

    MLX90640_SetRefreshRate(MLX_I2C_ADDR, rate_code_from_hz(MLX_REFRESH_HZ));
    MLX90640_SetResolution(MLX_I2C_ADDR, 3);          /* 18-bit ADC */
    MLX90640_SetChessMode(MLX_I2C_ADDR);

    ESP_LOGI(TAG, "MLX90640 ready (%d Hz)", MLX_REFRESH_HZ);

    const float emissivity = 0.95f;
    while (true) {
        if (MLX90640_GetFrameData(MLX_I2C_ADDR, s_frame_raw) < 0) {
            ESP_LOGW(TAG, "GetFrameData failed; backing off 100ms");
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        const float ta = MLX90640_GetTa(s_frame_raw, &s_params);
        const float tr = ta - 8.0f;
        MLX90640_CalculateTo(s_frame_raw, &s_params, emissivity, tr, s_back.temps_c);
        s_back.ts_ms = (uint32_t)(esp_timer_get_time() / 1000);

        if (xSemaphoreTake(s_mutex, portMAX_DELAY) == pdTRUE) {
            memcpy(&s_front, &s_back, sizeof(s_front));
            s_have_frame = true;
            xSemaphoreGive(s_mutex);
        }
    }
}

esp_err_t thermal_task_start(void)
{
    s_mutex = xSemaphoreCreateMutex();
    if (s_mutex == NULL) return ESP_ERR_NO_MEM;

    esp_err_t err = mlx_i2c_bus_init();
    if (err != ESP_OK) return err;

    BaseType_t r = xTaskCreatePinnedToCore(thermal_reader_task,
                                           "thermal", 8192, NULL,
                                           tskIDLE_PRIORITY + 2, NULL,
                                           tskNO_AFFINITY);
    return r == pdPASS ? ESP_OK : ESP_FAIL;
}

esp_err_t thermal_task_get_latest(thermal_frame_t *out)
{
    if (out == NULL) return ESP_ERR_INVALID_ARG;
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(50)) != pdTRUE)
        return ESP_ERR_TIMEOUT;

    esp_err_t err;
    if (!s_have_frame) {
        err = ESP_ERR_NOT_FOUND;
    } else {
        memcpy(out, &s_front, sizeof(*out));
        err = ESP_OK;
    }
    xSemaphoreGive(s_mutex);
    return err;
}
