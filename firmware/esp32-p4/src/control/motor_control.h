#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    float x;
    float y;
    float r;
    uint32_t ttl_ms;
} motor_control_manual_cmd_t;

typedef struct {
    float x;
    float y;
    float r;
    float wheel_fl;
    float wheel_fr;
    float wheel_bl;
    float wheel_br;
    uint32_t duty_fl;
    uint32_t duty_fr;
    uint32_t duty_bl;
    uint32_t duty_br;
    int64_t enc_fl;
    int64_t enc_fr;
    int64_t enc_bl;
    int64_t enc_br;
    uint32_t age_ms;
    bool active;
} motor_control_status_t;

esp_err_t motor_control_init(void);
esp_err_t motor_control_set_manual(const motor_control_manual_cmd_t *cmd);
void motor_control_stop(void);
void motor_control_get_status(motor_control_status_t *status);
