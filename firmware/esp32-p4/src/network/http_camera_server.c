#include "http_camera_server.h"

#include "camera_capture.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_http_server.h"
#include "esp_log.h"

static const char *TAG = "http_camera_server";

static esp_err_t root_handler(httpd_req_t *req)
{
    const char *body =
        "ESP32-P4 camera server\n"
        "\n"
        "GET /capture/visible.raw  - one captured frame as raw camera bytes\n"
        "GET /capture/visible.jpg  - placeholder until JPEG encoding is enabled\n";
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, body, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t capture_raw_handler(httpd_req_t *req)
{
    camera_frame_t frame = {0};
    esp_err_t ret = camera_capture_get_frame(&frame);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to capture frame: %s", esp_err_to_name(ret));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "camera capture failed");
        return ret;
    }

    httpd_resp_set_type(req, "application/octet-stream");
    httpd_resp_set_hdr(req, "X-Frame-Format", "camera-native");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    ret = httpd_resp_send(req, (const char *)frame.data, frame.length);

    esp_err_t release_ret = camera_capture_release_frame(&frame);
    if (release_ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to release frame: %s", esp_err_to_name(release_ret));
    }

    return ret;
}

static esp_err_t capture_jpg_handler(httpd_req_t *req)
{
    httpd_resp_set_status(req, "501 Not Implemented");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, "JPEG endpoint will be enabled after camera format/JPEG encoder setup.\nUse /capture/visible.raw for the first network test.\n");
}

esp_err_t http_camera_server_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;

    httpd_handle_t server = NULL;
    esp_err_t ret = httpd_start(&server, &config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server: %s", esp_err_to_name(ret));
        return ret;
    }

    const httpd_uri_t root_uri = {
        .uri = "/",
        .method = HTTP_GET,
        .handler = root_handler,
    };
    const httpd_uri_t capture_raw_uri = {
        .uri = "/capture/visible.raw",
        .method = HTTP_GET,
        .handler = capture_raw_handler,
    };
    const httpd_uri_t capture_jpg_uri = {
        .uri = "/capture/visible.jpg",
        .method = HTTP_GET,
        .handler = capture_jpg_handler,
    };

    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &root_uri), TAG, "Failed to register /");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &capture_raw_uri), TAG, "Failed to register raw capture");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &capture_jpg_uri), TAG, "Failed to register jpg capture");

    ESP_LOGI(TAG, "HTTP camera server started on port %d", config.server_port);
    return ESP_OK;
}
