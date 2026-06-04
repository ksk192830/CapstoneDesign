/*
 * ESP32 + MLX90640 thermal camera
 * --------------------------------
 * Streams every thermal frame as one newline-delimited JSON line over USB
 * serial:
 *
 *     {"ts":<millis>,"temps_c":[t0,t1,...,t767]}
 *
 * 768 floats, row-major (24 rows x 32 cols), units in Celsius.
 *
 * Wiring (ESP32 DevKit -> MLX90640 breakout):
 *     ESP32 3V3  -> MLX VIN
 *     ESP32 GND  -> MLX GND
 *     ESP32 D21  -> MLX SDA
 *     ESP32 D22  -> MLX SCL
 *   (ESP32-S3 / C3 boards may use different default I2C pins; adjust
 *    PIN_SDA / PIN_SCL below if your board does not expose 21/22.)
 *
 * Arduino IDE setup:
 *   1. Install the ESP32 board package: File -> Preferences -> Additional
 *      Boards Manager URLs:
 *          https://espressif.github.io/arduino-esp32/package_esp32_index.json
 *      then Tools -> Board -> Boards Manager -> install "esp32".
 *   2. Install library: Tools -> Manage Libraries... -> search
 *      "Adafruit MLX90640" -> Install (also pulls in Adafruit BusIO).
 *   3. Tools -> Board -> select your ESP32 variant (e.g. "ESP32 Dev Module").
 *   4. Tools -> Port -> select the /dev/cu.usbserial-* port.
 *   5. Upload (the IDE handles the boot/reset sequence automatically on
 *      most dev boards).
 *
 * Verifying on the host:
 *   Open the Serial Monitor at 921600 baud. After a short boot log you
 *   should see one JSON line per frame at the configured refresh rate
 *   (default 8 Hz = ~125 ms per line). The host parser should ignore any
 *   line that does not start with '{' to skip the ESP-IDF boot output.
 */

#include <Wire.h>
#include <Adafruit_MLX90640.h>

static const uint32_t SERIAL_BAUD = 921600;
static const uint8_t  PIN_SDA     = 21;
static const uint8_t  PIN_SCL     = 22;
static const uint32_t I2C_HZ      = 1000000;  // 1 MHz fast-mode-plus
static const mlx90640_refreshrate_t REFRESH = MLX90640_8_HZ;

Adafruit_MLX90640 mlx;
float frame[32 * 24];

static int refreshHz(mlx90640_refreshrate_t r) {
  switch (r) {
    case MLX90640_0_5_HZ: return 0;  // actually 0.5 Hz; reported as 0
    case MLX90640_1_HZ:   return 1;
    case MLX90640_2_HZ:   return 2;
    case MLX90640_4_HZ:   return 4;
    case MLX90640_8_HZ:   return 8;
    case MLX90640_16_HZ:  return 16;
    case MLX90640_32_HZ:  return 32;
    case MLX90640_64_HZ:  return 64;
  }
  return -1;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(100);
  Serial.println("{\"event\":\"boot\"}");

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(I2C_HZ);

  if (!mlx.begin(MLX90640_I2CADDR_DEFAULT, &Wire)) {
    Serial.println("{\"event\":\"error\",\"msg\":\"MLX90640 not detected on I2C\"}");
    while (true) { delay(1000); }
  }

  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(REFRESH);

  Serial.printf("{\"event\":\"ready\",\"refresh_hz\":%d,\"rows\":24,\"cols\":32}\n",
                refreshHz(REFRESH));
}

void loop() {
  if (mlx.getFrame(frame) != 0) {
    Serial.println("{\"event\":\"error\",\"msg\":\"frame read failed\"}");
    delay(50);
    return;
  }

  Serial.print("{\"ts\":");
  Serial.print(millis());
  Serial.print(",\"temps_c\":[");
  for (int i = 0; i < 768; i++) {
    Serial.print(frame[i], 2);
    if (i < 767) Serial.print(',');
  }
  Serial.println("]}");
}
