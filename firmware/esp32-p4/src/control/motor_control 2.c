#include "motor_control.h"

#include <math.h>
#include <stdbool.h>
#include <stdlib.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include "freertos/task.h"

#define WHEEL_RADIUS_MM 30.0f
#define TRACK_WIDTH_MM 255.0f
#define WHEEL_BASE_MM 200.0f

#define FL_PWM_PIN 23
#define FL_IN1_PIN 20
#define FL_IN2_PIN 6

#define BL_PWM_PIN 26
#define BL_IN3_PIN 24
#define BL_IN4_PIN 33

#define FR_PWM_PIN 25
#define FR_IN1_PIN 46
#define FR_IN2_PIN 27

#define BR_PWM_PIN 7
#define BR_IN3_PIN 4
#define BR_IN4_PIN 5

#define ENCODER_PPR 330

#define ENC_FL_A_PIN 3
#define ENC_FL_B_PIN 2
#define ENC_FR_A_PIN 32
#define ENC_FR_B_PIN 1
#define ENC_BL_A_PIN 53
#define ENC_BL_B_PIN 47
#define ENC_BR_A_PIN 48
#define ENC_BR_B_PIN 45

enum {
    MOTOR_PWM_FREQ_HZ = 20000,
    MOTOR_PWM_RES = LEDC_TIMER_10_BIT,
    MOTOR_PWM_MAX_DUTY = (1 << 10) - 1,
    MOTOR_DEFAULT_TTL_MS = 300,
    MOTOR_MAX_TTL_MS = 1000,
    MOTOR_SAFETY_PERIOD_MS = 50,
};

typedef enum {
    WHEEL_FL = 0,
    WHEEL_FR,
    WHEEL_BL,
    WHEEL_BR,
    WHEEL_COUNT,
} wheel_id_t;

typedef struct {
    gpio_num_t pwm_pin;
    gpio_num_t in_a_pin;
    gpio_num_t in_b_pin;
    int forward_a_level;
    int forward_b_level;
    ledc_channel_t pwm_channel;
} motor_hw_t;

typedef struct {
    gpio_num_t a_pin;
    gpio_num_t b_pin;
    volatile int64_t count;
    volatile uint8_t state;
} encoder_hw_t;

static const char *TAG = "motor_control";

static const motor_hw_t s_motors[WHEEL_COUNT] = {
    [WHEEL_FL] = {
        .pwm_pin = FL_PWM_PIN,
        .in_a_pin = FL_IN1_PIN,
        .in_b_pin = FL_IN2_PIN,
        .forward_a_level = 1,
        .forward_b_level = 0,
        .pwm_channel = LEDC_CHANNEL_0,
    },
    [WHEEL_FR] = {
        .pwm_pin = FR_PWM_PIN,
        .in_a_pin = FR_IN1_PIN,
        .in_b_pin = FR_IN2_PIN,
        .forward_a_level = 0,
        .forward_b_level = 1,
        .pwm_channel = LEDC_CHANNEL_1,
    },
    [WHEEL_BL] = {
        .pwm_pin = BL_PWM_PIN,
        .in_a_pin = BL_IN3_PIN,
        .in_b_pin = BL_IN4_PIN,
        .forward_a_level = 1,
        .forward_b_level = 0,
        .pwm_channel = LEDC_CHANNEL_2,
    },
    [WHEEL_BR] = {
        .pwm_pin = BR_PWM_PIN,
        .in_a_pin = BR_IN3_PIN,
        .in_b_pin = BR_IN4_PIN,
        .forward_a_level = 0,
        .forward_b_level = 1,
        .pwm_channel = LEDC_CHANNEL_3,
    },
};

static encoder_hw_t s_encoders[WHEEL_COUNT] = {
    [WHEEL_FL] = {.a_pin = ENC_FL_A_PIN, .b_pin = ENC_FL_B_PIN},
    [WHEEL_FR] = {.a_pin = ENC_FR_A_PIN, .b_pin = ENC_FR_B_PIN},
    [WHEEL_BL] = {.a_pin = ENC_BL_A_PIN, .b_pin = ENC_BL_B_PIN},
    [WHEEL_BR] = {.a_pin = ENC_BR_A_PIN, .b_pin = ENC_BR_B_PIN},
};

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static float s_last_x;
static float s_last_y;
static float s_last_r;
static float s_last_wheels[WHEEL_COUNT];
static int64_t s_last_command_us;
static uint32_t s_last_ttl_ms;
static bool s_active;

static float clampf(float v, float lo, float hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

static uint8_t encoder_read_state(const encoder_hw_t *enc)
{
    const int a = gpio_get_level(enc->a_pin) ? 1 : 0;
    const int b = gpio_get_level(enc->b_pin) ? 1 : 0;
    return (uint8_t)((a << 1) | b);
}

static void IRAM_ATTR encoder_isr(void *arg)
{
    encoder_hw_t *enc = (encoder_hw_t *)arg;
    static const int8_t transition_delta[16] = {
        0, -1, 1, 0,
        1, 0, 0, -1,
        -1, 0, 0, 1,
        0, 1, -1, 0,
    };

    const uint8_t next = encoder_read_state(enc);
    const uint8_t idx = (uint8_t)((enc->state << 2) | next);
    enc->count += transition_delta[idx];
    enc->state = next;
}

static esp_err_t configure_motor_gpio(void)
{
    uint64_t mask = 0;
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        mask |= 1ULL << s_motors[i].in_a_pin;
        mask |= 1ULL << s_motors[i].in_b_pin;
    }

    const gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    return gpio_config(&cfg);
}

static esp_err_t configure_pwm(void)
{
    const ledc_timer_config_t timer_cfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = MOTOR_PWM_RES,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = MOTOR_PWM_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_RETURN_ON_ERROR(ledc_timer_config(&timer_cfg), TAG, "LEDC timer config failed");

    for (int i = 0; i < WHEEL_COUNT; ++i) {
        const ledc_channel_config_t channel_cfg = {
            .gpio_num = s_motors[i].pwm_pin,
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = s_motors[i].pwm_channel,
            .intr_type = LEDC_INTR_DISABLE,
            .timer_sel = LEDC_TIMER_0,
            .duty = 0,
            .hpoint = 0,
        };
        ESP_RETURN_ON_ERROR(ledc_channel_config(&channel_cfg), TAG, "LEDC channel config failed");
    }

    return ESP_OK;
}

static esp_err_t configure_encoders(void)
{
    uint64_t mask = 0;
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        mask |= 1ULL << s_encoders[i].a_pin;
        mask |= 1ULL << s_encoders[i].b_pin;
    }

    const gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_ANYEDGE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&cfg), TAG, "encoder gpio config failed");

    esp_err_t ret = gpio_install_isr_service(ESP_INTR_FLAG_LEVEL1);
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_RETURN_ON_ERROR(ret, TAG, "gpio isr service install failed");
    }

    for (int i = 0; i < WHEEL_COUNT; ++i) {
        s_encoders[i].state = encoder_read_state(&s_encoders[i]);
        ESP_RETURN_ON_ERROR(gpio_isr_handler_add(s_encoders[i].a_pin, encoder_isr, &s_encoders[i]),
                            TAG,
                            "encoder A isr add failed");
        ESP_RETURN_ON_ERROR(gpio_isr_handler_add(s_encoders[i].b_pin, encoder_isr, &s_encoders[i]),
                            TAG,
                            "encoder B isr add failed");
    }

    return ESP_OK;
}

static void motor_apply_wheel(wheel_id_t wheel, float speed)
{
    const motor_hw_t *m = &s_motors[wheel];
    const float mag = fabsf(clampf(speed, -1.0f, 1.0f));
    const uint32_t duty = (uint32_t)lroundf(mag * MOTOR_PWM_MAX_DUTY);

    if (duty == 0) {
        gpio_set_level(m->in_a_pin, 0);
        gpio_set_level(m->in_b_pin, 0);
    } else if (speed > 0.0f) {
        gpio_set_level(m->in_a_pin, m->forward_a_level);
        gpio_set_level(m->in_b_pin, m->forward_b_level);
    } else {
        gpio_set_level(m->in_a_pin, !m->forward_a_level);
        gpio_set_level(m->in_b_pin, !m->forward_b_level);
    }

    ledc_set_duty(LEDC_LOW_SPEED_MODE, m->pwm_channel, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, m->pwm_channel);
}

static void motor_apply_all(const float wheels[WHEEL_COUNT])
{
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        motor_apply_wheel((wheel_id_t)i, wheels[i]);
    }
}

static void compute_wheels(float x, float y, float r, float wheels[WHEEL_COUNT])
{
    wheels[WHEEL_FL] = y + x - r;
    wheels[WHEEL_FR] = y - x + r;
    wheels[WHEEL_BL] = y - x - r;
    wheels[WHEEL_BR] = y + x + r;

    float max_abs = 1.0f;
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        const float a = fabsf(wheels[i]);
        if (a > max_abs) {
            max_abs = a;
        }
    }
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        wheels[i] /= max_abs;
    }
}

static void safety_task(void *arg)
{
    (void)arg;
    while (true) {
        bool expired = false;

        portENTER_CRITICAL(&s_lock);
        if (s_active) {
            const int64_t now_us = esp_timer_get_time();
            const uint32_t ttl_ms = s_last_ttl_ms == 0 ? MOTOR_DEFAULT_TTL_MS : s_last_ttl_ms;
            expired = (uint32_t)((now_us - s_last_command_us) / 1000) > ttl_ms;
            if (expired) {
                s_active = false;
                s_last_x = 0.0f;
                s_last_y = 0.0f;
                s_last_r = 0.0f;
                for (int i = 0; i < WHEEL_COUNT; ++i) {
                    s_last_wheels[i] = 0.0f;
                }
            }
        }
        portEXIT_CRITICAL(&s_lock);

        if (expired) {
            float zero[WHEEL_COUNT] = {0};
            motor_apply_all(zero);
        }

        vTaskDelay(pdMS_TO_TICKS(MOTOR_SAFETY_PERIOD_MS));
    }
}

esp_err_t motor_control_init(void)
{
    ESP_RETURN_ON_ERROR(configure_motor_gpio(), TAG, "motor gpio config failed");
    ESP_RETURN_ON_ERROR(configure_pwm(), TAG, "pwm config failed");
    ESP_RETURN_ON_ERROR(configure_encoders(), TAG, "encoder config failed");

    motor_control_stop();
    const BaseType_t task_ret = xTaskCreate(safety_task,
                                            "motor_safety",
                                            3072,
                                            NULL,
                                            tskIDLE_PRIORITY + 2,
                                            NULL);
    ESP_RETURN_ON_FALSE(task_ret == pdPASS, ESP_ERR_NO_MEM, TAG, "safety task create failed");

    ESP_LOGI(TAG,
             "initialized: radius=%.1fmm track=%.1fmm base=%.1fmm encoder=%d ppr",
             WHEEL_RADIUS_MM,
             TRACK_WIDTH_MM,
             WHEEL_BASE_MM,
             ENCODER_PPR);
    return ESP_OK;
}

esp_err_t motor_control_set_manual(const motor_control_manual_cmd_t *cmd)
{
    ESP_RETURN_ON_FALSE(cmd != NULL, ESP_ERR_INVALID_ARG, TAG, "null manual command");

    const float x = clampf(cmd->x, -1.0f, 1.0f);
    const float y = clampf(cmd->y, -1.0f, 1.0f);
    const float r = clampf(cmd->r, -1.0f, 1.0f);
    uint32_t ttl_ms = cmd->ttl_ms == 0 ? MOTOR_DEFAULT_TTL_MS : cmd->ttl_ms;
    if (ttl_ms > MOTOR_MAX_TTL_MS) {
        ttl_ms = MOTOR_MAX_TTL_MS;
    }

    float wheels[WHEEL_COUNT];
    compute_wheels(x, y, r, wheels);
    motor_apply_all(wheels);

    portENTER_CRITICAL(&s_lock);
    s_last_x = x;
    s_last_y = y;
    s_last_r = r;
    s_last_ttl_ms = ttl_ms;
    s_last_command_us = esp_timer_get_time();
    s_active = fabsf(x) > 0.001f || fabsf(y) > 0.001f || fabsf(r) > 0.001f;
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        s_last_wheels[i] = wheels[i];
    }
    portEXIT_CRITICAL(&s_lock);

    return ESP_OK;
}

void motor_control_stop(void)
{
    float zero[WHEEL_COUNT] = {0};
    motor_apply_all(zero);

    portENTER_CRITICAL(&s_lock);
    s_last_x = 0.0f;
    s_last_y = 0.0f;
    s_last_r = 0.0f;
    s_last_ttl_ms = MOTOR_DEFAULT_TTL_MS;
    s_last_command_us = esp_timer_get_time();
    s_active = false;
    for (int i = 0; i < WHEEL_COUNT; ++i) {
        s_last_wheels[i] = 0.0f;
    }
    portEXIT_CRITICAL(&s_lock);
}

void motor_control_get_status(motor_control_status_t *status)
{
    if (status == NULL) {
        return;
    }

    portENTER_CRITICAL(&s_lock);
    status->x = s_last_x;
    status->y = s_last_y;
    status->r = s_last_r;
    status->wheel_fl = s_last_wheels[WHEEL_FL];
    status->wheel_fr = s_last_wheels[WHEEL_FR];
    status->wheel_bl = s_last_wheels[WHEEL_BL];
    status->wheel_br = s_last_wheels[WHEEL_BR];
    status->enc_fl = s_encoders[WHEEL_FL].count;
    status->enc_fr = s_encoders[WHEEL_FR].count;
    status->enc_bl = s_encoders[WHEEL_BL].count;
    status->enc_br = s_encoders[WHEEL_BR].count;
    status->active = s_active;
    status->age_ms = (uint32_t)((esp_timer_get_time() - s_last_command_us) / 1000);
    portEXIT_CRITICAL(&s_lock);
}
