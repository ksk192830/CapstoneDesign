#include "http_camera_server.h"

#include <math.h>
#include <stdio.h>

#include "camera_capture.h"
#include "driver/jpeg_encode.h"
#include "esp_check.h"
#include "esp_err.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "thermal_task.h"

enum {
    CAMERA_STREAM_WIDTH = 800,
    CAMERA_STREAM_HEIGHT = 640,
    CAMERA_STREAM_JPEG_QUALITY = 40,
};

static const char *TAG = "http_camera_server";
static jpeg_encoder_handle_t s_jpeg_encoder;
static uint8_t *s_jpeg_output_buffer;
static uint32_t s_jpeg_output_buffer_size;

static esp_err_t ensure_jpeg_encoder(void)
{
    if (s_jpeg_encoder != NULL && s_jpeg_output_buffer != NULL) {
        return ESP_OK;
    }

    if (s_jpeg_encoder == NULL) {
        jpeg_encode_engine_cfg_t engine_cfg = {
            .intr_priority = 0,
            .timeout_ms = 5000,
        };
        ESP_RETURN_ON_ERROR(jpeg_new_encoder_engine(&engine_cfg, &s_jpeg_encoder), TAG, "failed to create jpeg encoder");
    }

    if (s_jpeg_output_buffer == NULL) {
        jpeg_encode_memory_alloc_cfg_t mem_cfg = {
            .buffer_direction = JPEG_DEC_ALLOC_OUTPUT_BUFFER,
        };

        size_t allocated_size = 0;
        s_jpeg_output_buffer = jpeg_alloc_encoder_mem(CAMERA_STREAM_WIDTH * CAMERA_STREAM_HEIGHT * 2, &mem_cfg, &allocated_size);
        ESP_RETURN_ON_FALSE(s_jpeg_output_buffer != NULL, ESP_ERR_NO_MEM, TAG, "failed to allocate jpeg output buffer");
        s_jpeg_output_buffer_size = (uint32_t)allocated_size;
    }

    return ESP_OK;
}

static esp_err_t root_handler(httpd_req_t *req)
{
    const char *body =
        "<!DOCTYPE html>"
        "<html>"
        "<head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
        "<title>ESP32-P4 Camera</title>"
        "<style>"
        "body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }"
        ".container { max-width: 900px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }"
        "h1 { color: #333; text-align: center; }"
        "img { display: block; width: 100%; border: 2px solid #ddd; border-radius: 4px; margin: 20px 0; background: #000; }"
        ".info { color: #666; text-align: center; }"
        ".status { padding: 10px; margin: 10px 0; border-radius: 4px; text-align: center; }"
        ".status.ok { background: #d4edda; color: #155724; }"
        ".status.error { background: #f8d7da; color: #721c24; }"
        ".fps { font-weight: bold; color: #007bff; }"
        "</style>"
        "</head>"
        "<body>"
        "<div class='container'>"
        "<h1>ESP32-P4 Camera Stream</h1>"
        "<img id='stream' src='/stream.mjpg' width='800' height='640' alt='camera stream'>"
        "<div class='status ok' id='status'>Connecting...</div>"
        "<div class='info'>Resolution: 800x640 | Format: MJPEG | Speed priority</div>"
        "</div>"
        "</body>"
        "</html>";

    httpd_resp_set_type(req, "text/html; charset=utf-8");
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
    httpd_resp_set_hdr(req, "X-Frame-Format", "RGB565");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    ret = httpd_resp_send(req, (const char *)frame.data, frame.length);

    esp_err_t release_ret = camera_capture_release_frame(&frame);
    if (release_ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to release frame: %s", esp_err_to_name(release_ret));
    }

    return ret;
}

static esp_err_t encode_frame_to_jpeg(const uint8_t *frame_data, uint32_t frame_length, uint32_t *out_size)
{
    esp_err_t ret = ensure_jpeg_encoder();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "JPEG encoder not ready: %s", esp_err_to_name(ret));
        return ret;
    }

    jpeg_encode_cfg_t jpeg_cfg = {
        .height = CAMERA_STREAM_HEIGHT,
        .width = CAMERA_STREAM_WIDTH,
        .src_type = JPEG_ENCODE_IN_FORMAT_RGB565,
        .sub_sample = JPEG_DOWN_SAMPLING_YUV422,
        .image_quality = CAMERA_STREAM_JPEG_QUALITY,
    };

    return jpeg_encoder_process(s_jpeg_encoder,
                                &jpeg_cfg,
                                (uint8_t *)frame_data,
                                frame_length,
                                s_jpeg_output_buffer,
                                s_jpeg_output_buffer_size,
                                out_size);
}

static esp_err_t capture_jpg_handler(httpd_req_t *req)
{
    camera_frame_t frame = {0};
    esp_err_t ret = camera_capture_get_frame(&frame);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to capture frame for JPEG: %s", esp_err_to_name(ret));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "camera capture failed");
        return ret;
    }

    uint32_t out_size = 0;
    ret = encode_frame_to_jpeg(frame.data, frame.length, &out_size);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "JPEG encode failed: %s", esp_err_to_name(ret));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "jpeg encode failed");
        (void)camera_capture_release_frame(&frame);
        return ret;
    }

    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    ret = httpd_resp_send(req, (const char *)s_jpeg_output_buffer, out_size);

    esp_err_t release_ret = camera_capture_release_frame(&frame);
    if (release_ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to release frame: %s", esp_err_to_name(release_ret));
    }

    return ret;
}


static esp_err_t stream_mjpg_handler(httpd_req_t *req)
{
    static const char *BOUNDARY = "--esp32p4frame\r\n";
    static const char *STREAM_TYPE = "multipart/x-mixed-replace;boundary=esp32p4frame";

    httpd_resp_set_type(req, STREAM_TYPE);
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");

    while (true) {
        camera_frame_t frame = {0};
        esp_err_t ret = camera_capture_get_frame(&frame);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to capture MJPEG frame: %s", esp_err_to_name(ret));
            return ret;
        }

        uint32_t out_size = 0;
        ret = encode_frame_to_jpeg(frame.data, frame.length, &out_size);
        esp_err_t release_ret = camera_capture_release_frame(&frame);
        if (release_ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to release MJPEG frame: %s", esp_err_to_name(release_ret));
        }

        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "MJPEG encode failed: %s", esp_err_to_name(ret));
            return ret;
        }

        char header[96];
        int header_len = snprintf(header,
                                  sizeof(header),
                                  "Content-Type: image/jpeg\r\nContent-Length: %lu\r\n\r\n",
                                  (unsigned long)out_size);
        if (header_len <= 0 || header_len >= (int)sizeof(header)) {
            return ESP_FAIL;
        }

        if (httpd_resp_send_chunk(req, BOUNDARY, HTTPD_RESP_USE_STRLEN) != ESP_OK ||
            httpd_resp_send_chunk(req, header, header_len) != ESP_OK ||
            httpd_resp_send_chunk(req, (const char *)s_jpeg_output_buffer, out_size) != ESP_OK ||
            httpd_resp_send_chunk(req, "\r\n", 2) != ESP_OK) {
            ESP_LOGD(TAG, "MJPEG client disconnected");
            return ESP_OK;
        }
    }
}

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

    char head[48];
    int hlen = snprintf(head, sizeof(head),
                        "{\"ts\":%lu,\"temps_c\":[",
                        (unsigned long)f.ts_ms);
    if (hlen < 0 || hlen >= (int)sizeof(head)) return ESP_FAIL;
    if (httpd_resp_send_chunk(req, head, hlen) != ESP_OK) return ESP_FAIL;

    char chunk[1024];
    int chunk_len = 0;
    for (int i = 0; i < MLX_PIXELS; ++i) {
        const float v = f.temps_c[i];
        const float safe = isfinite(v) ? v : 0.0f;
        const char *fmt = (i == MLX_PIXELS - 1) ? "%.2f" : "%.2f,";

        int wrote = snprintf(chunk + chunk_len,
                             sizeof(chunk) - chunk_len,
                             fmt, (double)safe);
        if (wrote < 0 || wrote >= (int)(sizeof(chunk) - chunk_len)) {
            if (chunk_len > 0) {
                if (httpd_resp_send_chunk(req, chunk, chunk_len) != ESP_OK) return ESP_FAIL;
                chunk_len = 0;
            }
            wrote = snprintf(chunk, sizeof(chunk), fmt, (double)safe);
            if (wrote < 0 || wrote >= (int)sizeof(chunk)) return ESP_FAIL;
        }
        chunk_len += wrote;
    }
    if (chunk_len > 0) {
        if (httpd_resp_send_chunk(req, chunk, chunk_len) != ESP_OK) return ESP_FAIL;
    }

    if (httpd_resp_send_chunk(req, "]}", 2) != ESP_OK) return ESP_FAIL;
    return httpd_resp_send_chunk(req, NULL, 0);  /* end of chunked response */
}

esp_err_t http_camera_server_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;
    /* thermal_frame_handler keeps a 3 KB thermal_frame_t on the stack
     * plus a 1 KB JSON chunk buffer; the 4 KB default overflows. */
    config.stack_size = 8192;

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
    const httpd_uri_t stream_mjpg_uri = {
        .uri = "/stream.mjpg",
        .method = HTTP_GET,
        .handler = stream_mjpg_handler,
    };
    const httpd_uri_t thermal_frame_uri = {
        .uri = "/thermal/frame",
        .method = HTTP_GET,
        .handler = thermal_frame_handler,
    };

    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &root_uri), TAG, "Failed to register /");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &capture_raw_uri), TAG, "Failed to register raw capture");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &capture_jpg_uri), TAG, "Failed to register jpg capture");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &stream_mjpg_uri), TAG, "Failed to register MJPEG stream");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &thermal_frame_uri), TAG, "Failed to register /thermal/frame");

    ESP_LOGD(TAG, "HTTP camera server started on port %d", config.server_port);
    return ESP_OK;
}
