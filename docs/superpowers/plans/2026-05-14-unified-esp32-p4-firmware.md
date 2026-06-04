# Unified ESP32-P4 Firmware Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify the ksk192830/CapstoneDesign ESP32-P4 firmware so a single board reads BOTH the OV5647 camera AND the MLX90640 thermal sensor, and exposes both over Wi-Fi (existing `GET /stream.mjpg` + new `GET /thermal/frame`). Then add an `HttpThermalSource` on the laptop side so `heat_algorithm` consumes thermal over HTTP instead of USB serial.

**Architecture:**
- Vendor Melexis's portable C MLX90640 driver as a local IDF component (no upstream ESP-IDF component exists).
- Implement the four I2C platform shims with ESP-IDF's modern `driver/i2c_master.h` on **I2C_NUM_1 @ 400 kHz** (P4's hard cap; gives ~4 Hz full-frame, matches our 8 Hz subpage target).
- A FreeRTOS task continuously refreshes a mutex-guarded latest-frame buffer; the HTTP handler snapshots it and returns JSON in the exact shape the existing Arduino sketch emits (`{"ts":..., "temps_c":[...]}`), so the laptop format-parser doesn't change.
- The laptop's `thermal.py` gains an `HttpThermalSource` (drop-in for `Esp32ThermalSource`); `heat_algorithm` chooses between them via a single constant.

**Tech Stack:** ESP-IDF v5.x via PlatformIO (pioarduino platform), C11, FreeRTOS, `esp_http_server`, `driver/i2c_master.h`, Melexis MLX90640 driver (Apache-2.0). Laptop side: Python 3.14, `urllib.request`, `numpy`, existing `cv2` integration.

**Hardware assumptions:**
- ESP32-P4 board with ESP32-C6 co-processor (Waveshare ESP32-P4-Module or equivalent — required for Wi-Fi).
- OV5647 / Pi Camera Rev 1.3 on MIPI CSI (already wired by user, already working in upstream firmware).
- MLX90640 breakout: VIN→3V3, GND→GND, **SDA→GPIO4, SCL→GPIO5** (default; configurable via `thermal_config.h`).

**Pin choice rationale:** GPIO 4/5 are free on the P4 — outside camera SCCB (7/8), Wi-Fi SDIO (14-19, 54), USB-JTAG default (24/25), strapping (34-38), and PSRAM/flash. If the user's board breakout doesn't expose 4/5, they edit `thermal_config.h`.

**Repo layout (all under this senior_capstone repo, no submodules):**
```
firmware/esp32-p4-unified/                  # local copy of GitHub firmware
├── components/
│   └── mlx90640/                           # NEW — vendored Melexis driver + shim
│       ├── CMakeLists.txt
│       ├── include/
│       │   ├── MLX90640_API.h
│       │   └── MLX90640_I2C_Driver.h
│       ├── MLX90640_API.c                  # vendored, unmodified
│       └── MLX90640_I2C_Driver.c           # NEW — our ESP-IDF i2c_master shim
├── src/
│   ├── main.c                              # MODIFIED — bring up thermal too
│   ├── camera/...                          # unchanged
│   ├── network/
│   │   ├── http_camera_server.c            # MODIFIED — add /thermal/frame
│   │   └── ...
│   ├── thermal/                            # NEW
│   │   ├── thermal_config.h                # GPIO + refresh rate config
│   │   ├── thermal_task.c                  # FreeRTOS reader task
│   │   └── thermal_task.h
│   └── CMakeLists.txt                      # MODIFIED — add thermal/ sources, mlx90640 dep
├── platformio.ini                          # unchanged
└── ...everything else                      # copied verbatim

thermal.py                                  # MODIFIED — add HttpThermalSource
heat_algorithm                              # MODIFIED — let user pick thermal transport
tests/                                      # NEW
└── test_http_thermal_source.py             # NEW — TDD coverage for the laptop side
```

**Testing strategy:**
- Laptop side: real TDD. Pytest tests for `HttpThermalSource` against a stub HTTP server.
- Firmware side: I cannot flash. The verification target is `pio run` succeeding (compile + link). Functional verification will happen when the user flashes and watches serial output.

---

## File Structure

**New firmware files (8):**
- `firmware/esp32-p4-unified/components/mlx90640/CMakeLists.txt` — component registration
- `firmware/esp32-p4-unified/components/mlx90640/include/MLX90640_API.h` — Melexis driver header (vendored)
- `firmware/esp32-p4-unified/components/mlx90640/include/MLX90640_I2C_Driver.h` — Melexis I2C shim header (vendored)
- `firmware/esp32-p4-unified/components/mlx90640/MLX90640_API.c` — Melexis driver source (vendored)
- `firmware/esp32-p4-unified/components/mlx90640/MLX90640_I2C_Driver.c` — our shim (NEW)
- `firmware/esp32-p4-unified/src/thermal/thermal_config.h` — pin & refresh constants
- `firmware/esp32-p4-unified/src/thermal/thermal_task.c` — reader task + buffer
- `firmware/esp32-p4-unified/src/thermal/thermal_task.h` — public API for main.c and http handler

**Modified firmware files (3):**
- `firmware/esp32-p4-unified/src/main.c` — call `thermal_task_start()` after Wi-Fi
- `firmware/esp32-p4-unified/src/network/http_camera_server.c` — register `/thermal/frame` handler
- `firmware/esp32-p4-unified/src/CMakeLists.txt` — add new SRCS

**New laptop files (1):**
- `tests/test_http_thermal_source.py` — pytest coverage

**Modified laptop files (2):**
- `thermal.py` — add `HttpThermalSource` class
- `heat_algorithm` — config switch between USB-serial and HTTP thermal sources

---

## Task Overview

| # | Task | Files |
|---|---|---|
| 1 | Scaffold local firmware copy | (clone) |
| 2 | Vendor Melexis MLX90640 driver | 4 vendored files |
| 3 | Write I2C shim + register the new component | 1 NEW shim, 1 NEW CMakeLists |
| 4 | Thermal config header | 1 NEW |
| 5 | Thermal reader task + buffer | 2 NEW |
| 6 | Wire thermal into main.c | 1 MOD |
| 7 | Add /thermal/frame HTTP handler | 1 MOD |
| 8 | Update src/CMakeLists.txt | 1 MOD |
| 9 | Compile-check firmware (`pio run`) | — |
| 10 | TDD: HttpThermalSource on laptop | 1 NEW test, 1 MOD |
| 11 | Wire heat_algorithm to choose source | 1 MOD |
| 12 | Smoke-test laptop side without hardware | — |

---

### Task 1: Scaffold local firmware copy

**Files:**
- Create directory: `firmware/esp32-p4-unified/` (cloned from upstream)

- [ ] **Step 1: Shallow-clone the upstream repo to a temp dir**

```bash
cd /tmp
rm -rf CapstoneDesign-src
git clone --depth=1 https://github.com/ksk192830/CapstoneDesign CapstoneDesign-src
```

Expected: clone succeeds.

- [ ] **Step 2: Copy `firmware/esp32-p4` into this project**

```bash
mkdir -p /Users/ethan/Desktop/SKKU/senior_capstone/firmware
cp -R /tmp/CapstoneDesign-src/firmware/esp32-p4 /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified
ls /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified
```

Expected: directory listing showing `platformio.ini`, `src/`, `CMakeLists.txt`, etc.

- [ ] **Step 3: Strip `.DS_Store` noise**

```bash
find /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified -name .DS_Store -delete
```

Expected: no output.

---

### Task 2: Vendor the Melexis MLX90640 driver

**Files:**
- Create: `firmware/esp32-p4-unified/components/mlx90640/CMakeLists.txt`
- Create: `firmware/esp32-p4-unified/components/mlx90640/include/MLX90640_API.h`
- Create: `firmware/esp32-p4-unified/components/mlx90640/include/MLX90640_I2C_Driver.h`
- Create: `firmware/esp32-p4-unified/components/mlx90640/MLX90640_API.c`

- [ ] **Step 1: Make the component directory tree**

```bash
mkdir -p /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified/components/mlx90640/include
```

- [ ] **Step 2: Download the four vendored files from Melexis**

```bash
base=https://raw.githubusercontent.com/melexis/mlx90640-library/master
dest=/Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified/components/mlx90640
curl -fsSL "$base/headers/MLX90640_API.h"        -o "$dest/include/MLX90640_API.h"
curl -fsSL "$base/headers/MLX90640_I2C_Driver.h" -o "$dest/include/MLX90640_I2C_Driver.h"
curl -fsSL "$base/functions/MLX90640_API.cpp"    -o "$dest/MLX90640_API.c"
ls -l "$dest/include" "$dest"
```

Expected: all four files non-empty. Note: Melexis ships `MLX90640_API.cpp` but the contents are C-compatible — we rename to `.c` so ESP-IDF's component build treats it as C (no C++ ABI overhead).

- [ ] **Step 3: Patch `MLX90640_API.c` to use C-style includes**

Read the file's first 10 lines:

```bash
head -10 /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified/components/mlx90640/MLX90640_API.c
```

If you see `#include <iostream>` or any C++-only headers, comment them out:

```bash
sed -i.bak 's|^#include *<iostream>.*$|/* removed for C build */|' /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified/components/mlx90640/MLX90640_API.c
rm /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified/components/mlx90640/MLX90640_API.c.bak
```

Expected: no remaining `<iostream>` in the file (`grep iostream MLX90640_API.c` returns nothing).

- [ ] **Step 4: Write the component CMakeLists**

Path: `firmware/esp32-p4-unified/components/mlx90640/CMakeLists.txt`

```cmake
idf_component_register(
    SRCS
        "MLX90640_API.c"
        "MLX90640_I2C_Driver.c"
    INCLUDE_DIRS
        "include"
    REQUIRES
        esp_driver_i2c
        log
)
```

Note: `MLX90640_I2C_Driver.c` does not exist yet — Task 3 creates it. The component is registered first so we can iterate.

---

### Task 3: Write the ESP-IDF i2c_master shim

**Files:**
- Create: `firmware/esp32-p4-unified/components/mlx90640/MLX90640_I2C_Driver.c`

The Melexis driver expects this contract: `MLX90640_I2CRead(addr, regStart, nWords, data)` writes a 2-byte big-endian register pointer with no STOP, then reads `nWords` 16-bit big-endian words. `MLX90640_I2CWrite(addr, regWriteAddr, word)` writes a 2-byte big-endian register pointer followed by a 2-byte big-endian payload. We map both to `i2c_master_transmit_receive` / `i2c_master_transmit`.

- [ ] **Step 1: Create the shim file**

Path: `firmware/esp32-p4-unified/components/mlx90640/MLX90640_I2C_Driver.c`

```c
#include "MLX90640_I2C_Driver.h"

#include <stdint.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

#include "thermal_config.h"   /* exposes MLX_I2C_PORT, SDA, SCL pins, freq */

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
    ESP_LOGI(TAG, "MLX90640 I2C bus up (port=%d sda=%d scl=%d %dHz)",
             MLX_I2C_PORT, MLX_I2C_SDA_PIN, MLX_I2C_SCL_PIN, s_scl_hz);
    return ESP_OK;
}

/* Melexis API shims --------------------------------------------------- */

void MLX90640_I2CInit(void)
{
    /* mlx_i2c_bus_init() is called explicitly from thermal_task_start. */
}

int MLX90640_I2CGeneralReset(void)
{
    /* General Call reset: addr 0x00, command 0x06. Optional; not all
       devices respond. We skip it — the MLX recovers fine without it. */
    return 0;
}

int MLX90640_I2CRead(uint8_t slaveAddr, uint16_t startAddress,
                     uint16_t nMemAddressRead, uint16_t *data)
{
    (void)slaveAddr;  /* device handle already bound to MLX_I2C_ADDR */
    if (s_dev_handle == NULL) return -1;

    uint8_t reg[2] = { (uint8_t)(startAddress >> 8), (uint8_t)(startAddress & 0xFF) };
    uint16_t total_bytes = (uint16_t)(nMemAddressRead * 2);

    /* esp_http_server has 1024 byte recv buffer; for MLX we read up to
       832 words (1664 bytes) for a frame. The i2c_master driver handles
       arbitrarily large transfers in one call. */
    uint8_t *raw = (uint8_t *)data;  /* reuse caller buffer to avoid alloc */
    esp_err_t err = i2c_master_transmit_receive(s_dev_handle,
                                                reg, sizeof(reg),
                                                raw, total_bytes, 200);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2CRead reg=0x%04x n=%u: %s",
                 startAddress, nMemAddressRead, esp_err_to_name(err));
        return -1;
    }

    /* Byte-swap each big-endian word to host (little-endian) in place. */
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
    /* freq is in kHz per Melexis convention. The P4 caps at 400 kHz; if
       caller asks higher we silently clamp. The bus must be re-init'd
       for a new frequency to take effect — currently a no-op because
       we bring the bus up once with the right frequency. */
    int hz = freq * 1000;
    if (hz > 400000) hz = 400000;
    s_scl_hz = hz;
}
```

- [ ] **Step 2: Add the exposed init declaration to `MLX90640_I2C_Driver.h`**

Append to `firmware/esp32-p4-unified/components/mlx90640/include/MLX90640_I2C_Driver.h` (before the closing `#endif`/`#ifdef __cplusplus` block if present, otherwise at the end):

```c
#ifdef __cplusplus
extern "C" {
#endif

/* ESP-IDF-specific: bring up the I2C bus and bind the MLX device.
 * Must be called before any MLX90640_* API call. */
esp_err_t mlx_i2c_bus_init(void);

#ifdef __cplusplus
}
#endif
```

Plus add the `esp_err.h` include at the top of that header. Use Edit, not Write — the Melexis file has its own header guard.

---

### Task 4: Thermal config header

**Files:**
- Create: `firmware/esp32-p4-unified/src/thermal/thermal_config.h`

- [ ] **Step 1: Make the directory**

```bash
mkdir -p /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified/src/thermal
```

- [ ] **Step 2: Write the config header**

Path: `firmware/esp32-p4-unified/src/thermal/thermal_config.h`

```c
#pragma once

#include "driver/gpio.h"
#include "driver/i2c_master.h"

/* MLX90640 I2C configuration. Camera SCCB owns I2C_NUM_0 on GPIO 7/8, so
 * the thermal sensor uses I2C_NUM_1 on a free pair. Override these here
 * if the user's wiring differs. ESP32-P4 caps I2C at 400 kHz. */
#define MLX_I2C_PORT     I2C_NUM_1
#define MLX_I2C_SDA_PIN  GPIO_NUM_4
#define MLX_I2C_SCL_PIN  GPIO_NUM_5
#define MLX_I2C_ADDR     0x33

/* Sensor refresh: 4 = 4 Hz (default), 8 Hz exceeds the 400 kHz I2C
 * budget for full-frame; we read in subpages to halve the bandwidth.
 * See Melexis datasheet §11.2.2.3. */
#define MLX_REFRESH_HZ   4

/* 768 floats: 24 rows x 32 cols. */
#define MLX_ROWS  24
#define MLX_COLS  32
#define MLX_PIXELS (MLX_ROWS * MLX_COLS)
```

---

### Task 5: Thermal reader task + thread-safe latest-frame buffer

**Files:**
- Create: `firmware/esp32-p4-unified/src/thermal/thermal_task.h`
- Create: `firmware/esp32-p4-unified/src/thermal/thermal_task.c`

- [ ] **Step 1: Write the header**

Path: `firmware/esp32-p4-unified/src/thermal/thermal_task.h`

```c
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "thermal_config.h"

typedef struct {
    uint32_t ts_ms;                    /* board millis() at frame end */
    float    temps_c[MLX_PIXELS];      /* 768 floats, row-major */
} thermal_frame_t;

/* Spawns the FreeRTOS reader task that keeps an internal frame buffer
 * up to date. Safe to call exactly once after Wi-Fi is up. */
esp_err_t thermal_task_start(void);

/* Snapshot the most recent complete frame into *out.
 * Returns ESP_OK on success, ESP_ERR_NOT_FOUND if no frame yet,
 * or whatever propagated from the mutex. */
esp_err_t thermal_task_get_latest(thermal_frame_t *out);
```

- [ ] **Step 2: Write the task implementation**

Path: `firmware/esp32-p4-unified/src/thermal/thermal_task.c`

```c
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

/* Internal double-buffer: writer task fills s_back, then under the
 * mutex swaps it into s_front. Readers (HTTP handler) copy s_front. */
static thermal_frame_t  s_front;
static thermal_frame_t  s_back;
static bool             s_have_frame = false;
static SemaphoreHandle_t s_mutex;

/* Per Melexis: eeMLX is 832 16-bit words, frame buffer is 834 words
 * (two subpages of 832 words minus overlap; the API requires 834). */
static uint16_t s_eeprom[832];
static uint16_t s_frame_raw[834];
static paramsMLX90640 s_params;

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

    /* refresh rate code: 0=0.5Hz, 1=1, 2=2, 3=4, 4=8, 5=16, 6=32, 7=64 */
    int rate_code = 3;  /* 4 Hz default */
    switch (MLX_REFRESH_HZ) {
        case 1:  rate_code = 1; break;
        case 2:  rate_code = 2; break;
        case 4:  rate_code = 3; break;
        case 8:  rate_code = 4; break;
        case 16: rate_code = 5; break;
        case 32: rate_code = 6; break;
        default: rate_code = 3; break;
    }
    MLX90640_SetRefreshRate(MLX_I2C_ADDR, rate_code);
    MLX90640_SetResolution(MLX_I2C_ADDR, 3);          /* 18-bit ADC */
    MLX90640_SetChessMode(MLX_I2C_ADDR);

    ESP_LOGI(TAG, "MLX90640 ready (%d Hz)", MLX_REFRESH_HZ);

    float emissivity = 0.95f;
    while (true) {
        if (MLX90640_GetFrameData(MLX_I2C_ADDR, s_frame_raw) < 0) {
            ESP_LOGW(TAG, "GetFrameData failed; backing off 100ms");
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        float vdd = MLX90640_GetVdd(s_frame_raw, &s_params);
        (void)vdd;
        float ta  = MLX90640_GetTa(s_frame_raw, &s_params);
        float tr  = ta - 8.0f;   /* reflection temperature; -8°C is the conventional offset */
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
```

---

### Task 6: Wire thermal_task_start into main.c

**Files:**
- Modify: `firmware/esp32-p4-unified/src/main.c`

- [ ] **Step 1: Add the include**

Use Edit to add this near the other local includes (after `#include "wifi_station.h"`):

```c
#include "thermal_task.h"
```

- [ ] **Step 2: Add the startup call after `[WIFI] connected`**

Find this block in `main.c`:

```c
    printf("[WIFI] connected\n");

    ret = camera_capture_init();
```

Insert between the two:

```c
    ret = thermal_task_start();
    if (ret != ESP_OK) {
        printf("[WARN] thermal task start failed: %s — continuing without thermal\n",
               esp_err_to_name(ret));
    } else {
        printf("[THERMAL] reader task running\n");
    }
```

Rationale for the non-fatal warn: a flaky MLX90640 (loose connector, wrong pins, missing pull-ups) should not stop the camera from working — we want the user to still see RGB and diagnose thermal separately.

- [ ] **Step 3: Update the final READY print**

Find:

```c
    printf("[READY] stream: http://%s/stream.mjpg\n", ip);
```

Add after it:

```c
    printf("[READY] thermal: http://%s/thermal/frame\n", ip);
```

---

### Task 7: Add `GET /thermal/frame` HTTP handler

**Files:**
- Modify: `firmware/esp32-p4-unified/src/network/http_camera_server.c`

The handler returns JSON in the exact shape the laptop's existing parser knows: `{"ts":<ms>,"temps_c":[t0,t1,...,t767]}`. We hand-format the floats to keep allocations minimal; 768 floats at 7 chars each = ~5.4 KB. Use chunked sends.

- [ ] **Step 1: Add includes near the top of `http_camera_server.c`**

```c
#include "thermal_task.h"

#include <math.h>
```

- [ ] **Step 2: Add the handler function (place above `http_camera_server_start`)**

```c
static esp_err_t thermal_frame_handler(httpd_req_t *req)
{
    thermal_frame_t f;
    esp_err_t err = thermal_task_get_latest(&f);
    if (err == ESP_ERR_NOT_FOUND) {
        httpd_resp_set_type(req, "application/json");
        httpd_resp_set_hdr(req, "Cache-Control", "no-store");
        const char *body = "{\"event\":\"warming_up\"}";
        return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
    }
    if (err != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "thermal unavailable");
        return err;
    }

    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");

    /* Build response in stack chunks to avoid one huge malloc. */
    char head[48];
    int hlen = snprintf(head, sizeof(head),
                        "{\"ts\":%lu,\"temps_c\":[",
                        (unsigned long)f.ts_ms);
    if (hlen < 0 || hlen >= (int)sizeof(head)) return ESP_FAIL;
    if (httpd_resp_send_chunk(req, head, hlen) != ESP_OK) return ESP_FAIL;

    /* Stream floats in 64-pixel chunks (~768 bytes per chunk). */
    char chunk[1024];
    int chunk_len = 0;
    for (int i = 0; i < MLX_PIXELS; ++i) {
        const float v = f.temps_c[i];
        /* sanitize: NaN/inf -> 0 so the laptop parser doesn't choke */
        const float safe = (isfinite(v) ? v : 0.0f);
        int wrote = snprintf(chunk + chunk_len,
                             sizeof(chunk) - chunk_len,
                             (i == MLX_PIXELS - 1) ? "%.2f" : "%.2f,",
                             (double)safe);
        if (wrote < 0 || wrote >= (int)(sizeof(chunk) - chunk_len)) {
            /* flush and retry this pixel */
            if (httpd_resp_send_chunk(req, chunk, chunk_len) != ESP_OK) return ESP_FAIL;
            chunk_len = 0;
            wrote = snprintf(chunk, sizeof(chunk),
                             (i == MLX_PIXELS - 1) ? "%.2f" : "%.2f,",
                             (double)safe);
            if (wrote < 0) return ESP_FAIL;
        }
        chunk_len += wrote;
    }
    if (chunk_len > 0) {
        if (httpd_resp_send_chunk(req, chunk, chunk_len) != ESP_OK) return ESP_FAIL;
    }

    const char *tail = "]}";
    if (httpd_resp_send_chunk(req, tail, 2) != ESP_OK) return ESP_FAIL;

    /* Signal end of chunked response. */
    return httpd_resp_send_chunk(req, NULL, 0);
}
```

- [ ] **Step 3: Register the route inside `http_camera_server_start`**

Find this block:

```c
    const httpd_uri_t stream_mjpg_uri = {
        .uri = "/stream.mjpg",
        .method = HTTP_GET,
        .handler = stream_mjpg_handler,
    };
```

Add after it:

```c
    const httpd_uri_t thermal_frame_uri = {
        .uri = "/thermal/frame",
        .method = HTTP_GET,
        .handler = thermal_frame_handler,
    };
```

Find the matching `httpd_register_uri_handler` calls and add:

```c
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &thermal_frame_uri),
                        TAG, "Failed to register /thermal/frame");
```

---

### Task 8: Update src/CMakeLists.txt

**Files:**
- Modify: `firmware/esp32-p4-unified/src/CMakeLists.txt`

- [ ] **Step 1: Add new sources and the mlx90640 dependency**

Replace the whole file:

```cmake
idf_component_register(
    SRCS
        "main.c"
        "camera/camera_capture.c"
        "network/http_camera_server.c"
        "network/wifi_station.c"
        "thermal/thermal_task.c"
    INCLUDE_DIRS
        "."
        "camera"
        "network"
        "thermal"
    REQUIRES
        esp_video
        esp_hosted
        esp_wifi_remote
        esp_driver_i2c
        esp_http_server
        esp_timer
        mlx90640
)
```

Adds: `thermal/thermal_task.c`, `thermal/` include dir, REQUIRES `esp_driver_i2c`, `esp_http_server`, `esp_timer`, and our local `mlx90640` component.

---

### Task 9: Compile-check the firmware

**Files:** (none directly modified — this is verification.)

- [ ] **Step 1: Move to the firmware dir**

```bash
cd /Users/ethan/Desktop/SKKU/senior_capstone/firmware/esp32-p4-unified
```

- [ ] **Step 2: Build it**

```bash
~/.local/bin/pio run 2>&1 | tee /tmp/pio_build.log | tail -60
```

Expected: succeeds with `SUCCESS` near the end of the log. First build downloads ~1 GB of toolchain and managed components — may take 5-15 minutes. Subsequent builds are seconds.

- [ ] **Step 3: If errors, classify them**

```bash
grep -E "error:|undefined reference|fatal error" /tmp/pio_build.log | head -20
```

Common likely failures:
- `'I2C_CLK_SRC_DEFAULT' undeclared` — IDF version older than the new `i2c_master` API; pioarduino's `platform-espressif32` stable should be ≥5.2, but check by looking at `dependencies.lock`.
- `undefined reference to MLX90640_Get*` — vendored driver missed a needed file; re-fetch.
- `undefined reference to mlx_i2c_bus_init` — `MLX90640_I2C_Driver.c` not in component sources; check `components/mlx90640/CMakeLists.txt`.
- `esp_ipa` IPA patch failed — re-run after `pio run -t clean` so the patch script re-applies.

Fix in place and rebuild. Do NOT proceed past this task until `pio run` succeeds.

---

### Task 10: TDD — `HttpThermalSource` on the laptop

**Files:**
- Create: `tests/test_http_thermal_source.py`
- Modify: `thermal.py`

- [ ] **Step 1: Install pytest if missing**

```bash
.venv/bin/python -m pip install pytest 2>&1 | tail -3
```

- [ ] **Step 2: Write the failing test**

Path: `tests/test_http_thermal_source.py`

```python
"""Tests for HttpThermalSource — polls /thermal/frame, hands ThermalFrame to consumers."""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thermal import HttpThermalSource, THERMAL_W, THERMAL_H  # noqa: E402


class _FakeEsp(BaseHTTPRequestHandler):
    """Test fixture: returns whatever JSON `self.server.payload` holds."""

    def log_message(self, *args, **kwargs):
        pass

    def do_GET(self):
        if self.path != "/thermal/frame":
            self.send_error(404)
            return
        body = self.server.payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeEsp)
    srv.payload = '{"event":"warming_up"}'
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        srv.shutdown()


def _good_frame_payload() -> str:
    temps = [20.0 + (i % 100) * 0.1 for i in range(THERMAL_W * THERMAL_H)]
    return json.dumps({"ts": 12345, "temps_c": temps})


def test_read_returns_ambient_until_first_frame_arrives(fake_server):
    url = f"http://127.0.0.1:{fake_server.server_address[1]}/thermal/frame"
    src = HttpThermalSource(url, poll_hz=20)
    try:
        # Server still returns warming_up — read() should give ambient placeholder.
        time.sleep(0.1)
        frame = src.read()
        assert frame.temps_c.shape == (THERMAL_H, THERMAL_W)
        assert np.allclose(frame.temps_c, 24.0)
    finally:
        src.close()


def test_read_returns_parsed_frame_once_payload_is_good(fake_server):
    fake_server.payload = _good_frame_payload()
    url = f"http://127.0.0.1:{fake_server.server_address[1]}/thermal/frame"
    src = HttpThermalSource(url, poll_hz=20)
    try:
        # Wait up to 1 s for the background thread to pick up a real frame.
        deadline = time.time() + 1.0
        while time.time() < deadline:
            f = src.read()
            if not np.allclose(f.temps_c, 24.0):
                break
            time.sleep(0.02)
        assert f.temps_c.shape == (THERMAL_H, THERMAL_W)
        assert f.temps_c.dtype == np.float32
        assert abs(float(f.temps_c[0, 0]) - 20.0) < 1e-3
        # Last pixel: index 767, (767 % 100) * 0.1 = 6.7 → 26.7
        assert abs(float(f.temps_c[-1, -1]) - 26.7) < 1e-3
    finally:
        src.close()


def test_read_survives_server_outage(fake_server):
    fake_server.payload = _good_frame_payload()
    url = f"http://127.0.0.1:{fake_server.server_address[1]}/thermal/frame"
    src = HttpThermalSource(url, poll_hz=20)
    try:
        time.sleep(0.2)
        first = src.read()
        assert first.temps_c.max() > 24.5

        # Stop the server mid-flight; read() must still return the
        # last good frame, not crash.
        fake_server.shutdown()
        time.sleep(0.1)
        f = src.read()
        assert f.temps_c.shape == (THERMAL_H, THERMAL_W)
    finally:
        src.close()
```

- [ ] **Step 3: Run the test, confirm it fails the right way**

```bash
cd /Users/ethan/Desktop/SKKU/senior_capstone
.venv/bin/python -m pytest tests/test_http_thermal_source.py -v 2>&1 | tail -15
```

Expected: ImportError on `HttpThermalSource` (not yet defined).

- [ ] **Step 4: Implement `HttpThermalSource` in `thermal.py`**

Append to `thermal.py`, after the existing `Esp32ThermalSource` class:

```python
import urllib.request
import urllib.error


class HttpThermalSource:
    """Polls `GET /thermal/frame` on the ESP32-P4 unified firmware.

    Wire format (matches `esp32_mlx90640.ino`):
        {"ts": <ms>, "temps_c": [t0, ..., t767]}
        or
        {"event": "warming_up"}  -> source returns ambient until real data arrives.

    A background thread keeps the latest frame fresh so `read()` never
    blocks on HTTP. Network errors are logged once per minute and the
    last good frame is held; we never raise from `read()`.
    """

    def __init__(self, url: str, poll_hz: float = 8.0, timeout: float = 1.0,
                 rows: int = THERMAL_H, cols: int = THERMAL_W):
        self.url = url
        self.timeout = float(timeout)
        self.rows = rows
        self.cols = cols
        self._period = 1.0 / max(0.5, float(poll_hz))
        self._latest: ThermalFrame | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_err_ts = 0.0
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[thermal] polling {url} @ ~{poll_hz:.0f} Hz")

    def _poll_loop(self) -> None:
        n_expected = self.rows * self.cols
        while not self._stop.is_set():
            t0 = time.time()
            try:
                with urllib.request.urlopen(self.url, timeout=self.timeout) as resp:
                    body = resp.read()
                data = json.loads(body.decode("utf-8", errors="ignore"))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                now = time.time()
                if now - self._last_err_ts > 60.0:
                    print(f"[thermal] http poll error: {e}")
                    self._last_err_ts = now
                self._sleep_to_period(t0)
                continue

            if isinstance(data, dict) and "event" in data:
                # warming_up etc. — leave _latest alone (may still be None)
                self._sleep_to_period(t0)
                continue

            temps = data.get("temps_c") if isinstance(data, dict) else None
            if not isinstance(temps, list) or len(temps) != n_expected:
                self._sleep_to_period(t0)
                continue

            arr = np.asarray(temps, dtype=np.float32).reshape(self.rows, self.cols)
            with self._lock:
                self._latest = ThermalFrame(temps_c=arr, timestamp=time.time())
            self._sleep_to_period(t0)

    def _sleep_to_period(self, started_at: float) -> None:
        elapsed = time.time() - started_at
        delay = self._period - elapsed
        if delay > 0:
            self._stop.wait(delay)

    def read(self) -> ThermalFrame:
        with self._lock:
            if self._latest is not None:
                return self._latest
        return ThermalFrame(
            temps_c=np.full((self.rows, self.cols), 24.0, dtype=np.float32),
            timestamp=time.time(),
        )

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
```

- [ ] **Step 5: Run tests, expect green**

```bash
.venv/bin/python -m pytest tests/test_http_thermal_source.py -v 2>&1 | tail -15
```

Expected: all 3 tests pass.

---

### Task 11: Let `heat_algorithm` pick its thermal transport

**Files:**
- Modify: `heat_algorithm`

- [ ] **Step 1: Add a constant + the new branch**

Find this block:

```python
# Real ESP32 + MLX90640 over USB serial. Set to None (or "") to use the
# mock thermal source for development without hardware.
THERMAL_PORT: str | None = "/dev/cu.usbmodem5B610374891"
THERMAL_BAUD = 921600
```

Replace with:

```python
# Thermal transport. Three options:
#   THERMAL_HTTP_URL: str  -> use HttpThermalSource against the unified
#       ESP32-P4 firmware (firmware/esp32-p4-unified). Set when the P4
#       is on Wi-Fi and exposing /thermal/frame.
#   THERMAL_PORT:     str  -> USB-serial source (legacy thermal-only
#       ESP32 running esp32_mlx90640.ino).
#   both None              -> MockThermalSource (Gaussian hot blob).
# Pick at most one; if both are set, HTTP wins.
THERMAL_HTTP_URL: str | None = None
THERMAL_PORT: str | None = "/dev/cu.usbmodem5B610374891"
THERMAL_BAUD = 921600
```

- [ ] **Step 2: Import HttpThermalSource**

Find the thermal import block:

```python
from thermal import (
    Esp32ThermalSource,
    MockThermalSource,
    THERMAL_W,
    THERMAL_H,
    detect_hotspot,
    project_thermal_to_rgb,
    render_thermal_view,
)
```

Add `HttpThermalSource,` after `Esp32ThermalSource,`.

- [ ] **Step 3: Update the source-selection block in `main()`**

Find this block:

```python
    if THERMAL_PORT:
        try:
            thermal = Esp32ThermalSource(THERMAL_PORT, THERMAL_BAUD)
        except Exception as e:
            print(f"[thermal] could not open {THERMAL_PORT} ({e}); falling back to mock")
            thermal = MockThermalSource()
    else:
        thermal = MockThermalSource()
```

Replace with:

```python
    if THERMAL_HTTP_URL:
        try:
            thermal = HttpThermalSource(THERMAL_HTTP_URL)
        except Exception as e:
            print(f"[thermal] could not reach {THERMAL_HTTP_URL} ({e}); falling back to mock")
            thermal = MockThermalSource()
    elif THERMAL_PORT:
        try:
            thermal = Esp32ThermalSource(THERMAL_PORT, THERMAL_BAUD)
        except Exception as e:
            print(f"[thermal] could not open {THERMAL_PORT} ({e}); falling back to mock")
            thermal = MockThermalSource()
    else:
        thermal = MockThermalSource()
```

---

### Task 12: Smoke-test the laptop side without hardware

**Files:** (none modified — verification only)

- [ ] **Step 1: Confirm the whole module still imports**

```bash
cd /Users/ethan/Desktop/SKKU/senior_capstone
.venv/bin/python -c "import importlib.util, sys; spec = importlib.util.spec_from_file_location('heat_algorithm','heat_algorithm'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('import OK')" 2>&1 | tail -5
```

Expected: `import OK`.

- [ ] **Step 2: Re-run the unit tests to make sure nothing regressed**

```bash
.venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 3: Stash a manual-test note for the user**

Tell the user: "Once you've flashed the unified firmware and noted the IP, edit `heat_algorithm`:
- Set `THERMAL_HTTP_URL = \"http://<p4-ip>/thermal/frame\"`
- Set `RGB_SOURCE = \"http://<p4-ip>/stream.mjpg\"`
Then `.venv/bin/python heat_algorithm`."

---

## Self-Review

**Spec coverage:**
- Camera over Wi-Fi → unchanged from upstream, preserved end-to-end. ✓
- MLX90640 reading inside the same P4 firmware → vendored Melexis driver + ESP-IDF shim + reader task. ✓
- Single board feeding both sensors → Task 6 wires both into `main.c`. ✓
- HTTP transport for thermal → Task 7. ✓
- Laptop consumes both → Task 10 (HttpThermalSource) + Task 11 (config switch). ✓
- "Don't merge into the GitHub repo" → Task 1 copies the firmware into our local repo, no submodule, no push. ✓
- TDD where possible → Task 10 follows red→green; firmware can't be unit-tested without flashing, but Task 9 establishes a hard compile-check gate. ✓

**Placeholder scan:** No "TBD" / "implement later" / "add validation" / "similar to Task N" — every step contains the code or command it requires.

**Type consistency:** `thermal_frame_t` is identical across `thermal_task.h` and `thermal_task.c`. `HttpThermalSource.read()` matches the `ThermalSource` Protocol shape used by `Esp32ThermalSource` / `MockThermalSource`. `THERMAL_W` / `THERMAL_H` referenced consistently. JSON wire format `{"ts":..., "temps_c":[...]}` matches what `Esp32ThermalSource._read_loop` already parses — the laptop format-parsing logic stays identical in shape.

**Known risks the engineer should flag immediately if hit:**
1. `MLX90640_API.cpp` may include other C++-only constructs beyond `<iostream>` — Task 2 Step 3 only scrubs that one header. If `pio run` shows other C++ errors, either keep the file as `.cpp` and add the IDF `register_component` line to treat it that way, or replace each remaining C++-ism (rare; Melexis writes mostly-C code).
2. The `patch_esp_ipa.py` pre-action depends on exact source text in the managed component. If `pio run -t clean && pio run` fails on the IPA patch, the upstream managed component may have shifted — check `dependencies.lock` and re-anchor the patch.
3. If the user's MLX90640 is wired to pins other than GPIO 4/5, edit `thermal_config.h` accordingly. We cannot detect this from outside the board.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-14-unified-esp32-p4-firmware.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints for review.

Given (a) the firmware portion can't be runtime-validated by me, (b) some tasks (vendoring + compile) are mechanical, and (c) you said "research, plan, and do" in one breath — I'm going to execute **inline**. I'll batch and check in at compile-check (after Task 9) and at green tests (after Task 10) so you can intervene if anything looks off.
