#include "MLX90640_I2C_Driver.h"

#include <stdint.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

#include "thermal_config.h"

static const char *TAG = "mlx_i2c";

static i2c_master_bus_handle_t s_bus_handle;
static i2c_master_dev_handle_t s_dev_handle;
static int                     s_scl_hz = 400000;

esp_err_t mlx_i2c_bus_init(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = MLX_I2C_PORT,
        .sda_io_num = MLX_I2C_SDA_PIN,
        .scl_io_num = MLX_I2C_SCL_PIN,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_bus_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2c_new_master_bus: %s", esp_err_to_name(err));
        return err;
    }

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = MLX_I2C_ADDR,
        .scl_speed_hz    = s_scl_hz,
    };
    err = i2c_master_bus_add_device(s_bus_handle, &dev_cfg, &s_dev_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2c_master_bus_add_device: %s", esp_err_to_name(err));
        return err;
    }
    ESP_LOGI(TAG, "MLX90640 I2C up (port=%d sda=%d scl=%d %d Hz)",
             MLX_I2C_PORT, MLX_I2C_SDA_PIN, MLX_I2C_SCL_PIN, s_scl_hz);
    return ESP_OK;
}

void MLX90640_I2CInit(void)
{
    /* mlx_i2c_bus_init() is called explicitly from thermal_task_start. */
}

int MLX90640_I2CGeneralReset(void)
{
    /* Optional general-call reset (addr 0x00, cmd 0x06). The MLX recovers
       without it; we skip rather than wrestle the master driver into
       general-call mode. */
    return 0;
}

int MLX90640_I2CRead(uint8_t slaveAddr, uint16_t startAddress,
                     uint16_t nMemAddressRead, uint16_t *data)
{
    (void)slaveAddr;  /* device handle is already bound to MLX_I2C_ADDR */
    if (s_dev_handle == NULL) return -1;

    uint8_t reg[2] = { (uint8_t)(startAddress >> 8),
                       (uint8_t)(startAddress & 0xFF) };
    uint16_t total_bytes = (uint16_t)(nMemAddressRead * 2);
    uint8_t *raw = (uint8_t *)data;
    esp_err_t err = i2c_master_transmit_receive(s_dev_handle,
                                                reg, sizeof(reg),
                                                raw, total_bytes, 200);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2CRead reg=0x%04x n=%u: %s",
                 startAddress, nMemAddressRead, esp_err_to_name(err));
        return -1;
    }

    /* Swap each big-endian word to host order in place. */
    for (uint16_t i = 0; i < nMemAddressRead; ++i) {
        uint8_t hi = raw[2 * i];
        uint8_t lo = raw[2 * i + 1];
        data[i] = ((uint16_t)hi << 8) | (uint16_t)lo;
    }
    return 0;
}

int MLX90640_I2CWrite(uint8_t slaveAddr, uint16_t writeAddress, uint16_t data)
{
    (void)slaveAddr;
    if (s_dev_handle == NULL) return -1;

    uint8_t buf[4] = {
        (uint8_t)(writeAddress >> 8), (uint8_t)(writeAddress & 0xFF),
        (uint8_t)(data         >> 8), (uint8_t)(data         & 0xFF),
    };
    esp_err_t err = i2c_master_transmit(s_dev_handle, buf, sizeof(buf), 200);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2CWrite reg=0x%04x val=0x%04x: %s",
                 writeAddress, data, esp_err_to_name(err));
        return -1;
    }
    return 0;
}

void MLX90640_I2CFreqSet(int freq)
{
    /* `freq` is in kHz per Melexis convention. ESP32-P4 caps at 400 kHz.
       The bus was already brought up at s_scl_hz; changing the rate at
       runtime is a no-op here. */
    int hz = freq * 1000;
    if (hz > 400000) hz = 400000;
    s_scl_hz = hz;
}
