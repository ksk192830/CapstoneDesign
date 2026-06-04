#include "wifi_station.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_check.h"
#include "esp_hosted.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_wifi_remote.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/timers.h"
#include "nvs_flash.h"
#include "wifi_credentials.h"

static const char *TAG = "wifi_station";

static EventGroupHandle_t s_wifi_event_group;
static const int WIFI_CONNECTED_BIT = BIT0;
static const int WIFI_FAIL_BIT = BIT1;
static int s_retry_count = 0;
static char s_ip_string[16] = "0.0.0.0";

// Exponential backoff for reason=201 (No AP found)
static uint8_t s_reason_201_count = 0;
static TimerHandle_t s_backoff_timer = NULL;
static const uint32_t BACKOFF_BASE_MS = 500;      // Initial backoff: 500ms
static const uint32_t BACKOFF_MAX_MS = 5000;      // Maximum backoff: 5s
static const uint8_t REASON_201_NO_AP_FOUND = 201;

static void backoff_timer_callback(TimerHandle_t xTimer)
{
    (void)xTimer;
    esp_wifi_remote_connect();
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == WIFI_REMOTE_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_remote_connect();
    } else if (event_base == WIFI_REMOTE_EVENT && event_id == WIFI_EVENT_STA_CONNECTED) {
    } else if (event_base == WIFI_REMOTE_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *event = (wifi_event_sta_disconnected_t *)event_data;
        uint8_t reason = event != NULL ? event->reason : 0;
        bool was_connected = strcmp(s_ip_string, "0.0.0.0") != 0;
        if (was_connected) {
            printf("[WARN] Wi-Fi disconnected, reason=%d\n", reason);
        }
        
        // Handle reason=201 (No AP found) with exponential backoff
        if (reason == REASON_201_NO_AP_FOUND && s_reason_201_count < 5) {
            uint32_t backoff_ms = BACKOFF_BASE_MS * (1U << s_reason_201_count);
            if (backoff_ms > BACKOFF_MAX_MS) {
                backoff_ms = BACKOFF_MAX_MS;
            }
            
            // Create backoff timer if not already created
            if (s_backoff_timer == NULL) {
                s_backoff_timer = xTimerCreate("wifi_backoff", pdMS_TO_TICKS(backoff_ms),
                                               pdFALSE, NULL, backoff_timer_callback);
            } else {
                xTimerChangePeriod(s_backoff_timer, pdMS_TO_TICKS(backoff_ms), 0);
            }
            
            if (s_backoff_timer != NULL) {
                xTimerStart(s_backoff_timer, 0);
                s_reason_201_count++;
            } else {
                ESP_LOGE(TAG, "Failed to create backoff timer");
                esp_wifi_remote_connect();
            }
        } else if (reason != REASON_201_NO_AP_FOUND && s_retry_count < 5) {
            // Other disconnect reasons: immediate retry, reset reason_201 count
            s_reason_201_count = 0;
            esp_wifi_remote_connect();
            s_retry_count++;
        } else if (reason == REASON_201_NO_AP_FOUND || s_retry_count >= 5) {
            // Max retries exhausted
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        snprintf(s_ip_string, sizeof(s_ip_string), IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_count = 0;
        s_reason_201_count = 0;  // Reset backoff counter on successful connection
        if (s_backoff_timer != NULL) {
            xTimerStop(s_backoff_timer, 0);
            xTimerDelete(s_backoff_timer, 0);
            s_backoff_timer = NULL;
        }
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

esp_err_t wifi_station_connect(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_RETURN_ON_ERROR(nvs_flash_erase(), TAG, "Failed to erase NVS");
        ret = nvs_flash_init();
    }
    ESP_RETURN_ON_ERROR(ret, TAG, "Failed to initialize NVS");

    s_wifi_event_group = xEventGroupCreate();
    if (s_wifi_event_group == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "Failed to initialize netif");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "Failed to create event loop");
    esp_netif_t *sta_netif = esp_netif_create_default_wifi_sta();
    ESP_RETURN_ON_FALSE(sta_netif != NULL, ESP_FAIL, TAG, "Failed to create default Wi-Fi STA netif");

    ESP_RETURN_ON_ERROR((esp_err_t)esp_hosted_init(), TAG, "Failed to initialize ESP-Hosted");
    ESP_RETURN_ON_ERROR((esp_err_t)esp_hosted_connect_to_slave(), TAG, "Failed to connect ESP-Hosted slave");

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_remote_init(&cfg), TAG, "Failed to initialize remote Wi-Fi");

    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_REMOTE_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL), TAG, "Failed to register remote Wi-Fi event handler");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL), TAG, "Failed to register IP event handler");

    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, WIFI_STA_SSID, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, WIFI_STA_PASSWORD, sizeof(wifi_config.sta.password));

    ESP_RETURN_ON_ERROR(esp_wifi_remote_set_mode(WIFI_MODE_STA), TAG, "Failed to set remote Wi-Fi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_remote_set_config(WIFI_IF_STA, &wifi_config), TAG, "Failed to set remote Wi-Fi config");
    ESP_RETURN_ON_ERROR(esp_wifi_remote_start(), TAG, "Failed to start remote Wi-Fi");

    printf("[WIFI] connecting to SSID: %s\n", WIFI_STA_SSID);

    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT, pdFALSE, pdFALSE, pdMS_TO_TICKS(60000));
    if (bits & WIFI_CONNECTED_BIT) {
        return ESP_OK;
    }

    return ESP_FAIL;
}

const char *wifi_station_get_ip_string(void)
{
    return s_ip_string;
}

